# finance/views.py
from datetime import date
import calendar
import uuid
import json
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Sum, Value, DecimalField, Q, F, Case, When
from django.db.models.functions import Coalesce
from django.shortcuts import render, redirect
from django.urls import reverse
from django.contrib import messages

from .models import Category, Subcategory, Account, Transaction, MonthlyBudget, CreditCard, ActionLog, BudgetTemplate, BudgetTemplateItem


def log_action(user, action, details=''):
    """
    Registra uma ação do usuário no log.
    
    Args:
        user: Usuário que executou a ação
        action: Descrição da ação executada
        details: Detalhes adicionais da ação (opcional)
    """
    ActionLog.objects.create(
        user=user,
        action=action,
        details=details
    )


def _get_year_month_from_request(request, use_session=False, session_key_prefix=''):
    """
    Lê year/month do GET, com fallback para sessão (se use_session=True) ou mês atual.
    
    Args:
        request: HttpRequest object
        use_session: Se True, salva/recupera valores da sessão
        session_key_prefix: Prefixo para as chaves da sessão (ex: 'report_', 'budget_')
    """
    today = date.today()
    
    # Tenta obter dos parâmetros GET primeiro
    year_from_get = request.GET.get('year')
    month_from_get = request.GET.get('month')
    
    if year_from_get is not None or month_from_get is not None:
        # Se há parâmetros GET, usa eles e salva na sessão se solicitado
        try:
            year = int(year_from_get) if year_from_get else today.year
        except ValueError:
            year = today.year
        try:
            month = int(month_from_get) if month_from_get else today.month
        except ValueError:
            month = today.month
        
        # Salva na sessão se solicitado
        if use_session:
            request.session[f'{session_key_prefix}year'] = year
            request.session[f'{session_key_prefix}month'] = month
        
        return year, month
    
    # Se não há parâmetros GET, tenta recuperar da sessão
    if use_session:
        year = request.session.get(f'{session_key_prefix}year', today.year)
        month = request.session.get(f'{session_key_prefix}month', today.month)
        return year, month
    
    # Fallback para mês atual
    return today.year, today.month

def add_months(d, months):
    """Adiciona N meses à data, ajustando o dia para o último dia do mês se necessário."""
    month = d.month - 1 + months
    year = d.year + month // 12
    month = month % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)

def calculate_invoice_due_date(transaction_date, closing_day, due_day):
    """
    Calcula a data de vencimento da fatura do cartão de crédito baseada na data da transação,
    no dia de fechamento e no dia de vencimento.
    
    Regra:
    1. Primeiro identifica qual fatura a transação pertence (baseado no closing_day):
       - Se a data da transação for antes ou igual ao dia de fechamento do mês atual,
         a fatura fecha no mês atual.
       - Se a data da transação for depois do dia de fechamento,
         a fatura fecha no próximo mês.
    
    2. Depois calcula a data de vencimento (baseado no due_day):
       - Se due_day >= closing_day, o vencimento está no mesmo mês que o fechamento.
       - Se due_day < closing_day, o vencimento está no próximo mês após o fechamento.
    """
    year = transaction_date.year
    month = transaction_date.month
    
    # Passo 1: Identificar o mês em que a fatura fecha
    if transaction_date.day <= closing_day:
        # Fatura fecha no mês atual
        closing_month = month
        closing_year = year
    else:
        # Fatura fecha no próximo mês
        closing_month = month + 1
        closing_year = year
        if closing_month > 12:
            closing_month = 1
            closing_year = year + 1
    
    # Passo 2: Calcular a data de vencimento
    if due_day >= closing_day:
        # Vencimento está no mesmo mês que o fechamento
        due_month = closing_month
        due_year = closing_year
    else:
        # Vencimento está no próximo mês após o fechamento
        due_month = closing_month + 1
        due_year = closing_year
        if due_month > 12:
            due_month = 1
            due_year = closing_year + 1
    
    # Ajusta o dia de vencimento para o último dia do mês se necessário
    max_day = calendar.monthrange(due_year, due_month)[1]
    final_due_day = min(due_day, max_day)
    
    return date(due_year, due_month, final_due_day)

def calculate_credit_card_invoices(user, year, month):
    """
    Calcula o total das faturas de cada cartão de crédito para um mês/ano específico.
    Retorna uma lista ordenada com informações sobre cada fatura, incluindo status de pagamento.
    """
    from decimal import Decimal
    credit_cards = CreditCard.objects.all().order_by('name')
    invoices = []
    
    for card in credit_cards:
        # Buscar todas as transações com esse cartão onde payment_date está no mês/ano
        all_transactions = Transaction.objects.filter(
            credit_card=card,
            payment_date__year=year,
            payment_date__month=month,
            type=Transaction.TYPE_EXPENSE
        )
        
        total = all_transactions.aggregate(
            total=Coalesce(Sum('amount'), Value(0), output_field=DecimalField())
        )['total'] or Decimal('0.00')
        
        # Verificar se todas as transações estão pagas
        paid_count = all_transactions.filter(is_paid=True).count()
        total_count = all_transactions.count()
        is_paid = total_count > 0 and paid_count == total_count
        
        # Adicionar à lista mesmo se não houver transações (mostrar R$ 0,00)
        invoices.append({
            'card': card,
            'total': total,
            'count': total_count,
            'is_paid': is_paid,
        })
    
    return invoices

# Transaction page
@login_required
def transactions_view(request):
    """
    Página para:
    - listar últimos lançamentos
    - cadastrar novo lançamento (receita/despesa)
    """
    user = request.user

    if request.method == 'POST':
        date_str = request.POST.get('date')
        amount_str = request.POST.get('amount')
        type_ = request.POST.get('type')
        subcategory_id = request.POST.get('subcategory')  # Mudou de category para subcategory
        # account_id = request.POST.get('account')
        description = request.POST.get('description', '').strip()
        comment = request.POST.get('comment', '').strip()

        # CAMPOS PARA PARCELAMENTO
        is_installment = request.POST.get('is_installment') == 'on'
        installments_str = request.POST.get('installments') or '1'
        
        # CAMPO PARA CARTÃO DE CRÉDITO
        credit_card_id = request.POST.get('credit_card', '').strip()
        
        # CAMPO PARA TAG DO PROPRIETÁRIO
        owner_tag = request.POST.get('owner_tag', '').strip()

        # Validações simples
        if not date_str or not amount_str or not type_ or not subcategory_id: #or not account_id:
            messages.error(request, "Preencha todos os campos obrigatórios.")
            return redirect('finance:transactions')

        try:
            from datetime import datetime
            t_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            messages.error(request, "Data inválida.")
            return redirect('finance:transactions')

        try:
            from decimal import Decimal
            amount = Decimal(amount_str.replace(',', '.'))
        except Exception:
            messages.error(request, "Valor inválido.")
            return redirect('finance:transactions')
        
        try:
            installments = int(installments_str)
        except ValueError:
            installments = 1

        if installments < 1:
            installments = 1

        try:
            subcategory = Subcategory.objects.get(id=subcategory_id)
            # A categoria será identificada automaticamente através da subcategoria no método save()
            # account = Account.objects.get(id=account_id, user=user)
            account = Account.objects.get(id=2)
        except (Subcategory.DoesNotExist, Account.DoesNotExist):
            messages.error(request, "Subcategoria ou conta não encontrada.")
            return redirect('finance:transactions')

        # Buscar cartão de crédito se informado
        credit_card = None
        if credit_card_id:
            try:
                credit_card = CreditCard.objects.get(id=credit_card_id)
            except CreditCard.DoesNotExist:
                messages.error(request, "Cartão de crédito não encontrado.")
                return redirect('finance:transactions')
        
        # Validar tag do proprietário se o cartão é Bradesco
        if credit_card and 'bradesco' in credit_card.name.lower():
            if not owner_tag or owner_tag not in [Transaction.OWNER_THI, Transaction.OWNER_THA]:
                messages.error(request, "É obrigatório selecionar a Tag (Thi ou Tha) para lançamentos no cartão Bradesco.")
                return redirect('finance:transactions')
        else:
            # Se não for Bradesco, não deve ter tag
            owner_tag = None

        from decimal import Decimal, ROUND_HALF_UP

        if is_installment and installments > 1:
            # Gera um ID único para o grupo de parcelas
            group_id = uuid.uuid4()

            # Verificar se o valor informado é o total ou o valor de cada parcela
            amount_type = request.POST.get('amount_type', 'total')
            
            if amount_type == 'installment':
                # Valor informado é o valor de cada parcela
                # Calculamos o valor total multiplicando pela quantidade de parcelas
                total_amount = amount * installments
                # Cada parcela terá o mesmo valor informado
                valores = [amount for _ in range(installments)]
            else:
                # Valor informado é o TOTAL da compra (comportamento padrão)
                # Calculamos o valor de cada parcela (ajustando a última pelo arredondamento)
                base_parcela = (amount / installments).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                valores = [base_parcela for _ in range(installments)]
                diferenca = amount - sum(valores)
                # Compensa diferença na última parcela (quando a divisão não é exata em centavos)
                valores[-1] += diferenca
                total_amount = amount

            created_transaction_ids = []
            for i in range(installments):
                # Data de lançamento: data original incrementada pelos meses
                parcela_date = add_months(t_date, i)
                # Data de pagamento: se houver cartão de crédito, calcula a data de vencimento; senão, usa a mesma data
                if credit_card:
                    parcela_payment_date = calculate_invoice_due_date(parcela_date, credit_card.closing_day, credit_card.due_day)
                else:
                    parcela_payment_date = parcela_date
                
                parcela_descricao = f"{description} (parcela {i+1}/{installments})" if description else f"Parcela {i+1}/{installments}"
                # Se não tem cartão de crédito, marca como paga. Se tem cartão, fica como não paga até pagar a fatura.
                is_paid_value = not bool(credit_card)
                transaction = Transaction.objects.create(
                    user=user,
                    date=parcela_date,
                    payment_date=parcela_payment_date,
                    amount=valores[i],
                    type=type_,
                    subcategory=subcategory,
                    account=account,
                    description=parcela_descricao,
                    comment=comment,
                    owner_tag=owner_tag,
                    installment_group=group_id,
                    is_installment=True,
                    credit_card=credit_card,
                    is_paid=is_paid_value,
                )
                created_transaction_ids.append(transaction.id)

            messages.success(request, f"Compra parcelada lançada em {installments} parcelas.")
            # Salvar data na sessão para manter no próximo lançamento
            request.session['last_transaction_date'] = date_str
            # Registrar log
            payment_method = credit_card.name if credit_card else "Débito"
            log_action(
                user,
                f"Criou compra parcelada: {description or 'Sem descrição'} ({installments} parcelas de R$ {valores[0]:.2f})",
                f"ID do grupo: {group_id}, Total: R$ {total_amount:.2f}, Subcategoria: {subcategory.name}, Conta: {account.name}, Forma de pagamento: {payment_method}"
            )
            # Determinar payment_method para preservar o filtro na tabela
            payment_method_param = credit_card_id if credit_card_id else 'debit'
            # Redireciona com os IDs das transações criadas e preserva o filtro de método de pagamento
            ids_param = ','.join(map(str, created_transaction_ids))
            return redirect(f"{reverse('finance:transactions')}?highlight={ids_param}&payment_method={payment_method_param}")
        else:
            # Lançamento normal (uma única transação)
            # date = data de lançamento (data informada pelo usuário)
            # payment_date = se houver cartão de crédito, data de vencimento; senão, mesma data
            if credit_card:
                payment_date = calculate_invoice_due_date(t_date, credit_card.closing_day, credit_card.due_day)
            else:
                payment_date = t_date
            
            # Se não tem cartão de crédito, marca como paga. Se tem cartão, fica como não paga até pagar a fatura.
            is_paid_value = not bool(credit_card)
            transaction = Transaction.objects.create(
                user=user,
                date=t_date,
                payment_date=payment_date,
                amount=amount,
                type=type_,
                subcategory=subcategory,
                account=account,
                description=description,
                comment=comment,
                owner_tag=owner_tag,
                is_installment=False,
                credit_card=credit_card,
                is_paid=is_paid_value,
            )
            messages.success(request, "Lançamento salvo com sucesso.")
            # Salvar data na sessão para manter no próximo lançamento
            request.session['last_transaction_date'] = date_str
            # Registrar log
            payment_method = credit_card.name if credit_card else "Débito"
            log_action(
                user,
                f"Criou lançamento: {description or 'Sem descrição'} ({transaction.get_type_display()})",
                f"Valor: R$ {amount:.2f}, Data: {t_date}, Subcategoria: {subcategory.name}, Conta: {account.name}, Forma de pagamento: {payment_method}"
            )
            # Determinar payment_method para preservar o filtro na tabela
            payment_method_param = credit_card_id if credit_card_id else 'debit'
            # Redireciona com o ID da transação criada e preserva o filtro de método de pagamento
            return redirect(f"{reverse('finance:transactions')}?highlight={transaction.id}&payment_method={payment_method_param}")

    # GET
    subcategories = Subcategory.objects.all().select_related('category').order_by('category__name', 'name')
    accounts = Account.objects.all().order_by('name')
    credit_cards = CreditCard.objects.all().order_by('name')
    
    # Obter mês/ano para exibição das faturas de cartão de crédito
    # Usa sessão específica para manter o valor entre recarregamentos
    year, month = _get_year_month_from_request(request, use_session=True, session_key_prefix='invoice_')
    
    # Verificar se deve mostrar mês seguinte
    show_next_month = request.GET.get('next_month') == '1'
    if show_next_month:
        # Calcular mês seguinte
        if month == 12:
            filter_year = year + 1
            filter_month = 1
        else:
            filter_year = year
            filter_month = month + 1
    else:
        filter_year = year
        filter_month = month
    
    # Filtrar transações pelo mês selecionado
    transactions = (
        Transaction.objects
        .filter(payment_date__year=filter_year, payment_date__month=filter_month)
        .select_related('subcategory', 'subcategory__category', 'account', 'credit_card')
    )

    # Filtro por forma de pagamento (nav)
    payment_method = request.GET.get('payment_method', '')
    selected_card = None
    is_bradesco_selected = False
    if payment_method == 'debit':
        transactions = transactions.filter(credit_card__isnull=True)
    else:
        try:
            card_id = int(payment_method)
            transactions = transactions.filter(credit_card_id=card_id)
            # Verificar se é Bradesco
            try:
                selected_card = CreditCard.objects.get(id=card_id)
                is_bradesco_selected = 'bradesco' in selected_card.name.lower()
            except CreditCard.DoesNotExist:
                pass
        except (TypeError, ValueError):
            # Se vazio ou inválido, não filtra por cartão
            pass

    # Filtro por owner_tag (Tag) - apenas quando Bradesco está selecionado e uma tag foi escolhida
    owner_tag_filter = request.GET.get('owner_tag', '')
    if owner_tag_filter and owner_tag_filter in [Transaction.OWNER_THI, Transaction.OWNER_THA]:
        transactions = transactions.filter(owner_tag=owner_tag_filter)

    total_signed_amount = transactions.aggregate(
        total=Coalesce(
            Sum(
                Case(
                    When(type=Transaction.TYPE_EXPENSE, then=F('amount') * Value(-1)),
                    default=F('amount'),
                    output_field=DecimalField(max_digits=14, decimal_places=2),
                )
            ),
            Value(0),
            output_field=DecimalField(max_digits=14, decimal_places=2),
        )
    )['total']

    # Ordenar: não parcelados primeiro, parcelados por último, depois por data e ID
    transactions = transactions.order_by('is_installment', '-date', '-id')
    
    # Obter última data usada da sessão, ou usar data de hoje
    last_date = request.session.get('last_transaction_date')
    if not last_date:
        last_date = date.today().strftime('%Y-%m-%d')
    
    # Calcular faturas dos cartões de crédito
    credit_card_invoices = calculate_credit_card_invoices(user, year, month)

    context = {
        'subcategories': subcategories,
        'accounts': accounts,
        'credit_cards': credit_cards,
        'transactions': transactions,
        'total_signed_amount': total_signed_amount,
        'credit_card_invoices': credit_card_invoices,
        'selected_year': year,
        'selected_month': month,
        'filter_year': filter_year,
        'filter_month': filter_month,
        'show_next_month': show_next_month,
        'payment_method': payment_method,
        'owner_tag_filter': owner_tag_filter,
        'is_bradesco_selected': is_bradesco_selected,
        'default_date': last_date,
    }
    return render(request, 'finance/transactions.html', context)


@login_required
def delete_transaction_view(request, transaction_id):
    """
    Deleta uma transação específica.
    Apenas aceita requisições POST por segurança.
    """
    if request.method != 'POST':
        messages.error(request, "Método não permitido.")
        return redirect('finance:transactions')
    
    user = request.user
    
    try:
        transaction = Transaction.objects.get(id=transaction_id)
        # Registrar log antes de deletar
        payment_method = transaction.credit_card.name if transaction.credit_card else "Débito"
        log_action(
            user,
            f"Deletou lançamento: {transaction.description or 'Sem descrição'}",
            f"ID: {transaction_id}, Valor: R$ {transaction.amount:.2f}, Tipo: {transaction.get_type_display()}, Data: {transaction.date}, Forma de pagamento: {payment_method}"
        )
        transaction.delete()
        messages.success(request, "Lançamento deletado com sucesso.")
    except Transaction.DoesNotExist:
        messages.error(request, "Lançamento não encontrado.")
    
    return redirect('finance:transactions')


@login_required
def bulk_delete_transactions_view(request):
    """
    Deleta múltiplas transações em lote.
    Apenas aceita requisições POST por segurança.
    """
    if request.method != 'POST':
        messages.error(request, "Método não permitido.")
        return redirect('finance:all_transactions')
    
    user = request.user
    transaction_ids = request.POST.getlist('transaction_ids')
    
    if not transaction_ids:
        messages.error(request, "Nenhum lançamento selecionado para deletar.")
    else:
        deleted_count = 0
        failed_count = 0
        
        for transaction_id in transaction_ids:
            try:
                transaction = Transaction.objects.get(id=transaction_id)
                # Registrar log antes de deletar
                payment_method = transaction.credit_card.name if transaction.credit_card else "Débito"
                log_action(
                    user,
                    f"Deletou lançamento (lote): {transaction.description or 'Sem descrição'}",
                    f"ID: {transaction_id}, Valor: R$ {transaction.amount:.2f}, Tipo: {transaction.get_type_display()}, Data: {transaction.date}, Forma de pagamento: {payment_method}"
                )
                transaction.delete()
                deleted_count += 1
            except Transaction.DoesNotExist:
                failed_count += 1
        
        if deleted_count > 0:
            if deleted_count == 1:
                messages.success(request, f"{deleted_count} lançamento deletado com sucesso.")
            else:
                messages.success(request, f"{deleted_count} lançamentos deletados com sucesso.")
        
        if failed_count > 0:
            messages.warning(request, f"{failed_count} lançamento(s) não puderam ser deletados.")
    
    # Reconstruir URL de retorno com os filtros preservados
    from urllib.parse import urlencode
    filter_params = {}
    for key in ['year', 'month', 'type', 'credit_card', 'status', 'subcategory', 'installment', 'owner_tag']:
        value = request.POST.get(key)
        if value:
            filter_params[key] = value
    
    if filter_params:
        return_url = reverse('finance:all_transactions') + '?' + urlencode(filter_params)
    else:
        return_url = reverse('finance:all_transactions')
    
    return redirect(return_url)


@login_required
def edit_transaction_view(request, transaction_id):
    """
    Edita uma transação existente.
    """
    user = request.user
    
    try:
        transaction = Transaction.objects.get(id=transaction_id)
    except Transaction.DoesNotExist:
        messages.error(request, "Lançamento não encontrado.")
        return redirect('finance:transactions')
    
    if request.method == 'POST':
        date_str = request.POST.get('date')
        amount_str = request.POST.get('amount')
        type_ = request.POST.get('type')
        subcategory_id = request.POST.get('subcategory')  # Mudou de category para subcategory
        account_id = request.POST.get('account')
        description = request.POST.get('description', '').strip()
        comment = request.POST.get('comment', '').strip()
        credit_card_id = request.POST.get('credit_card', '').strip()
        owner_tag = request.POST.get('owner_tag', '').strip()
        
        # Validações
        if not date_str or not amount_str or not type_ or not subcategory_id or not account_id:
            messages.error(request, "Preencha todos os campos obrigatórios.")
            next_param = request.GET.get('next', '')
            redirect_url = reverse('finance:edit_transaction', args=[transaction_id])
            if next_param:
                redirect_url += f'?next={next_param}'
            return redirect(redirect_url)
        
        try:
            from datetime import datetime
            t_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            messages.error(request, "Data inválida.")
            next_param = request.GET.get('next', '')
            redirect_url = reverse('finance:edit_transaction', args=[transaction_id])
            if next_param:
                redirect_url += f'?next={next_param}'
            return redirect(redirect_url)
        
        try:
            from decimal import Decimal
            amount = Decimal(amount_str.replace(',', '.'))
        except Exception:
            messages.error(request, "Valor inválido.")
            next_param = request.GET.get('next', '')
            redirect_url = reverse('finance:edit_transaction', args=[transaction_id])
            if next_param:
                redirect_url += f'?next={next_param}'
            return redirect(redirect_url)
        
        try:
            subcategory = Subcategory.objects.get(id=subcategory_id)
            account = Account.objects.get(id=account_id)
        except (Subcategory.DoesNotExist, Account.DoesNotExist):
            messages.error(request, "Subcategoria ou conta não encontrada.")
            next_param = request.GET.get('next', '')
            redirect_url = reverse('finance:edit_transaction', args=[transaction_id])
            if next_param:
                redirect_url += f'?next={next_param}'
            return redirect(redirect_url)
        
        # Buscar cartão de crédito se informado
        credit_card = None
        if credit_card_id:
            try:
                credit_card = CreditCard.objects.get(id=credit_card_id)
            except CreditCard.DoesNotExist:
                messages.error(request, "Cartão de crédito não encontrado.")
                next_param = request.GET.get('next', '')
                redirect_url = reverse('finance:edit_transaction', args=[transaction_id])
                if next_param:
                    redirect_url += f'?next={next_param}'
                return redirect(redirect_url)
        
        # Validar tag do proprietário se o cartão é Bradesco
        if credit_card and 'bradesco' in credit_card.name.lower():
            if not owner_tag or owner_tag not in [Transaction.OWNER_THI, Transaction.OWNER_THA]:
                messages.error(request, "É obrigatório selecionar a Tag (Thi ou Tha) para lançamentos no cartão Bradesco.")
                next_param = request.GET.get('next', '')
                redirect_url = reverse('finance:edit_transaction', args=[transaction_id])
                if next_param:
                    redirect_url += f'?next={next_param}'
                return redirect(redirect_url)
        else:
            # Se não for Bradesco, não deve ter tag
            owner_tag = None
        
        # Atualizar transação
        transaction.date = t_date
        transaction.amount = amount
        transaction.type = type_
        transaction.subcategory = subcategory
        # A categoria será atualizada automaticamente através do método save() do model
        transaction.account = account
        transaction.description = description
        transaction.comment = comment
        transaction.owner_tag = owner_tag
        
        # Ajustar is_paid apenas se mudou de ter/ não ter cartão de crédito
        had_credit_card = transaction.credit_card is not None
        will_have_credit_card = credit_card is not None
        
        if had_credit_card and not will_have_credit_card:
            # Removeu cartão de crédito - marca como paga
            transaction.is_paid = True
        elif not had_credit_card and will_have_credit_card:
            # Adicionou cartão de crédito - marca como não paga
            transaction.is_paid = False
        
        transaction.credit_card = credit_card
        
        # Calcular payment_date
        if credit_card:
            transaction.payment_date = calculate_invoice_due_date(t_date, credit_card.closing_day, credit_card.due_day)
        else:
            transaction.payment_date = t_date
        
        transaction.save()
        # Registrar log
        payment_method = credit_card.name if credit_card else "Débito"
        log_action(
            user,
            f"Editou lançamento: {description or 'Sem descrição'}",
            f"ID: {transaction_id}, Valor: R$ {amount:.2f}, Tipo: {type_}, Data: {t_date}, Subcategoria: {subcategory.name}, Forma de pagamento: {payment_method}"
        )
        messages.success(request, "Lançamento atualizado com sucesso.")
        
        # Redirecionar para a página de origem se especificada
        from urllib.parse import unquote
        next_url = request.GET.get('next') or request.POST.get('next')
        if next_url:
            # Se next_url é um nome de view, fazer redirect direto
            if next_url == 'transactions':
                return redirect('finance:transactions')
            elif next_url == 'all_transactions':
                return redirect('finance:all_transactions')
            else:
                # Decodificar URL se foi codificada
                decoded_url = unquote(next_url)
                # Caso contrário, assumir que é uma URL completa (pode ser relativa ou absoluta)
                try:
                    return redirect(decoded_url)
                except:
                    # Se falhar, usar fallback
                    return redirect('finance:transactions')
        
        # Fallback padrão
        return redirect('finance:transactions')
    
    # GET - mostrar formulário de edição
    subcategories = Subcategory.objects.all().select_related('category').order_by('category__name', 'name')
    accounts = Account.objects.all().order_by('name')
    credit_cards = CreditCard.objects.all().order_by('name')
    
    # Converter o valor Decimal para string com ponto como separador decimal
    # Campos number do HTML precisam usar ponto (.) não vírgula (,) como separador decimal
    if transaction.amount is not None:
        # Converter Decimal para float e depois para string, garantindo ponto como separador
        transaction_amount = str(float(transaction.amount)).replace(',', '.')
    else:
        transaction_amount = ''
    
    context = {
        'transaction': transaction,
        'transaction_amount': transaction_amount,
        'subcategories': subcategories,
        'accounts': accounts,
        'credit_cards': credit_cards,
    }
    return render(request, 'finance/edit_transaction.html', context)


@login_required
def pay_credit_card_invoice_view(request, card_id, year, month):
    """
    View para confirmar e efetuar o pagamento da fatura de um cartão de crédito.
    """
    user = request.user
    
    try:
        card = CreditCard.objects.get(id=card_id)
    except CreditCard.DoesNotExist:
        messages.error(request, "Cartão de crédito não encontrado.")
        return redirect('finance:transactions')
    
    # Buscar transações da fatura desse mês/ano
    transactions = Transaction.objects.filter(
        credit_card=card,
        payment_date__year=year,
        payment_date__month=month,
        type=Transaction.TYPE_EXPENSE,
        is_paid=False  # Apenas as não pagas
    )
    
    if not transactions.exists():
        messages.info(request, f"Não há fatura pendente para o cartão {card.name} em {month:02d}/{year}.")
        return redirect('finance:transactions')
    
    total = transactions.aggregate(
        total=Coalesce(Sum('amount'), Value(0), output_field=DecimalField())
    )['total'] or 0
    
    if request.method == 'POST':
        # Efetuar pagamento - marcar todas as transações como pagas
        # Usar save() individual para disparar signals e atualizar saldo das contas
        for transaction in transactions:
            transaction.is_paid = True
            transaction.save()
        # Registrar log
        log_action(
            user,
            f"Pagou fatura do cartão {card.name}",
            f"Mês/Ano: {month:02d}/{year}, Total: R$ {total:.2f}, {transactions.count()} transações"
        )
        messages.success(
            request, 
            f"Fatura do cartão {card.name} de {month:02d}/{year} no valor de R$ {total:.2f} foi paga com sucesso."
        )
        return redirect('finance:transactions')
    
    # GET - mostrar confirmação
    context = {
        'card': card,
        'year': year,
        'month': month,
        'total': total,
        'transaction_count': transactions.count(),
    }
    return render(request, 'finance/pay_invoice.html', context)


@login_required
def reopen_credit_card_invoice_view(request, card_id, year, month):
    """
    View para reabrir (desmarcar pagamento) da fatura de um cartão de crédito.
    """
    user = request.user
    
    try:
        card = CreditCard.objects.get(id=card_id)
    except CreditCard.DoesNotExist:
        messages.error(request, "Cartão de crédito não encontrado.")
        return redirect('finance:transactions')
    
    # Buscar transações pagas da fatura desse mês/ano
    transactions = Transaction.objects.filter(
        credit_card=card,
        payment_date__year=year,
        payment_date__month=month,
        type=Transaction.TYPE_EXPENSE,
        is_paid=True  # Apenas as pagas
    )
    
    if not transactions.exists():
        messages.info(request, f"Não há fatura paga para reabrir do cartão {card.name} em {month:02d}/{year}.")
        return redirect('finance:transactions')
    
    total = transactions.aggregate(
        total=Coalesce(Sum('amount'), Value(0), output_field=DecimalField())
    )['total'] or 0
    
    if request.method == 'POST':
        # Reabrir fatura - marcar todas as transações como não pagas
        # Usar save() individual para disparar signals e atualizar saldo das contas
        for transaction in transactions:
            transaction.is_paid = False
            transaction.save()
        # Registrar log
        log_action(
            user,
            f"Reabriu fatura do cartão {card.name}",
            f"Mês/Ano: {month:02d}/{year}, Total: R$ {total:.2f}, {transactions.count()} transações"
        )
        messages.success(
            request, 
            f"Fatura do cartão {card.name} de {month:02d}/{year} no valor de R$ {total:.2f} foi reaberta."
        )
        return redirect('finance:transactions')
    
    # GET - mostrar confirmação
    context = {
        'card': card,
        'year': year,
        'month': month,
        'total': total,
        'transaction_count': transactions.count(),
    }
    return render(request, 'finance/reopen_invoice.html', context)


@login_required
def budget_view(request):
    """
    Página de planejamento de orçamento mensal por categoria.
    - GET: mostra formulário (todas as categorias) com valores do orçamento (se existirem)
    - POST: salva/atualiza os orçamentos
    """
    user = request.user
    today = date.today()

    if request.method == 'POST':
        year = int(request.POST.get('year', today.year))
        month = int(request.POST.get('month', today.month))
        
        # Salvar na sessão compartilhada
        request.session['shared_year'] = year
        request.session['shared_month'] = month

        subcategories = Subcategory.objects.all().order_by('category__name', 'name')

        for subcategory in subcategories:
            field_name = f'budget_{subcategory.id}'
            value_str = request.POST.get(field_name, '').strip()
            if value_str == '':
                # Se vazio, podemos considerar como 0 ou simplesmente ignorar.
                amount = None
            else:
                try:
                    from decimal import Decimal
                    amount = Decimal(value_str.replace(',', '.'))
                except Exception:
                    messages.error(request, f"Valor inválido para subcategoria {subcategory.name}.")
                    return redirect(f"{reverse('finance:budget')}?year={year}&month={month}")

            # Criar/atualizar orçamento
            if amount is None:
                # Se quiser deletar orçamento quando vazio:
                budget_exists = MonthlyBudget.objects.filter(
                    subcategory=subcategory, year=year, month=month
                ).exists()
                MonthlyBudget.objects.filter(
                    subcategory=subcategory, year=year, month=month
                ).delete()
                if budget_exists:
                    log_action(
                        user,
                        f"Deletou orçamento: {subcategory.name}",
                        f"Mês/Ano: {month:02d}/{year}"
                    )
            else:
                budget, created = MonthlyBudget.objects.update_or_create(
                    user=user,
                    subcategory=subcategory,
                    year=year,
                    month=month,
                    defaults={'amount': amount},
                )
                action = "Criou" if created else "Atualizou"
                log_action(
                    user,
                    f"{action} orçamento: {subcategory.name}",
                    f"Mês/Ano: {month:02d}/{year}, Valor: R$ {amount:.2f}"
                )

        messages.success(request, "Orçamento salvo com sucesso.")
        return redirect(f"{reverse('finance:budget')}?year={year}&month={month}")

    # GET
    year, month = _get_year_month_from_request(request, use_session=True, session_key_prefix='shared_')
    subcategories = Subcategory.objects.select_related('category').all()
    budgets = MonthlyBudget.objects.filter(year=year, month=month).select_related('subcategory')

    # Criar um dicionário mapeando subcategory_id para o objeto MonthlyBudget
    budget_map = {}
    for budget in budgets:
        budget_map[budget.subcategory_id] = budget

    # Agrupar subcategorias por categoria
    categories_dict = {}
    
    for subcat in subcategories:
        category_id = subcat.category.id
        category_name = subcat.category.name
        category_is_income = subcat.category.is_income
        
        # Inicializar categoria se não existir
        if category_id not in categories_dict:
            categories_dict[category_id] = {
                'category_id': category_id,
                'category_name': category_name,
                'category_is_income': category_is_income,
                'subcategories': [],
            }
        
        # Adicionar subcategoria com o orçamento correspondente
        budget = budget_map.get(subcat.id)
        subcat_dict = {
            'id': subcat.id,
            'name': subcat.name,
            'budget_amount': budget.amount if budget else None,
        }
        categories_dict[category_id]['subcategories'].append(subcat_dict)
    
    # Ordenar categorias: primeiro Receitas (is_income=True), depois Despesas (is_income=False)
    # Dentro de cada grupo, ordenar alfabeticamente
    sorted_categories = sorted(
        categories_dict.values(),
        key=lambda c: (
            not c.get('category_is_income', False),  # False (Receitas) vem primeiro, True (Despesas) vem depois
            (c['category_name'] or 'Sem categoria').lower()
        )
    )
    
    # Ordenar subcategorias dentro de cada categoria alfabeticamente
    for cat in sorted_categories:
        cat['subcategories'].sort(key=lambda s: (s.get('name') or 'Sem nome').lower())

    context = {
        'year': year,
        'month': month,
        'categories': sorted_categories,
        'budget_map': budget_map,
    }
    return render(request, 'finance/budget.html', context)


@login_required
def report_view(request):
    """
    Página de relatório: Gasto x Orçado por subcategoria no mês.
    Também permite editar orçamentos (unificado com Planejamento).
    """
    user = request.user
    today = date.today()
    
    # Tratamento de POST (salvar orçamentos)
    if request.method == 'POST':
        year = int(request.POST.get('year', today.year))
        month = int(request.POST.get('month', today.month))
        
        # Salvar na sessão compartilhada
        request.session['shared_year'] = year
        request.session['shared_month'] = month

        subcategories = Subcategory.objects.all().order_by('category__name', 'name')

        for subcategory in subcategories:
            field_name = f'budget_{subcategory.id}'
            comment_field_name = f'comment_{subcategory.id}'
            value_str = request.POST.get(field_name, '').strip()
            comment_str = request.POST.get(comment_field_name, '').strip()
            
            if value_str == '':
                # Se vazio, deletar orçamento
                amount = None
            else:
                try:
                    from decimal import Decimal
                    amount = Decimal(value_str.replace(',', '.'))
                except Exception:
                    messages.error(request, f"Valor inválido para subcategoria {subcategory.name}.")
                    return redirect(f"{reverse('finance:report')}?year={year}&month={month}&edit=1")

            # Criar/atualizar orçamento
            if amount is None:
                # Deletar orçamento quando vazio
                budget_exists = MonthlyBudget.objects.filter(
                    subcategory=subcategory, year=year, month=month
                ).exists()
                MonthlyBudget.objects.filter(
                    subcategory=subcategory, year=year, month=month
                ).delete()
                if budget_exists:
                    log_action(
                        user,
                        f"Deletou orçamento: {subcategory.name}",
                        f"Mês/Ano: {month:02d}/{year}"
                    )
            else:
                # Verificar se o orçamento já existe e se houve mudança
                try:
                    existing_budget = MonthlyBudget.objects.get(
                        user=user,
                        subcategory=subcategory,
                        year=year,
                        month=month
                    )
                    # Comparar valores e comentários
                    amount_changed = existing_budget.amount != amount
                    comment_value = comment_str if comment_str else None
                    comment_changed = existing_budget.comment != comment_value
                    
                    if amount_changed or comment_changed:
                        # Atualizar apenas se houver mudança
                        existing_budget.amount = amount
                        existing_budget.comment = comment_value
                        existing_budget.save()
                        log_action(
                            user,
                            f"Atualizou orçamento: {subcategory.name}",
                            f"Mês/Ano: {month:02d}/{year}, Valor: R$ {amount:.2f}"
                        )
                except MonthlyBudget.DoesNotExist:
                    # Criar novo orçamento
                    MonthlyBudget.objects.create(
                        user=user,
                        subcategory=subcategory,
                        year=year,
                        month=month,
                        amount=amount,
                        comment=comment_str if comment_str else None
                    )
                    log_action(
                        user,
                        f"Criou orçamento: {subcategory.name}",
                        f"Mês/Ano: {month:02d}/{year}, Valor: R$ {amount:.2f}"
                    )

        messages.success(request, "Orçamento salvo com sucesso.")
        return redirect(f"{reverse('finance:report')}?year={year}&month={month}")
    
    # GET - exibir relatório
    year, month = _get_year_month_from_request(request, use_session=True, session_key_prefix='shared_')
    
    # Verificar se está no modo edição
    is_edit_mode = request.GET.get('edit') == '1'

    # Transações por subcategoria (Receitas e Despesas)
    transactions_qs = (
        Transaction.objects
        .filter(
            payment_date__year=year,
            payment_date__month=month,
        )
        .values('subcategory_id', 'subcategory__name', 'subcategory__category_id', 'subcategory__category__name', 'subcategory__category__is_income', 'type')
        .annotate(amount_sum=Coalesce(Sum('amount'), Value(0), output_field=DecimalField(max_digits=14, decimal_places=2)))
    )

    budgets_qs = (
        MonthlyBudget.objects
        .filter(year=year, month=month)
        .select_related('subcategory', 'subcategory__category')
        .values('subcategory_id', 'subcategory__name', 'subcategory__category_id', 'subcategory__category__name', 'subcategory__category__is_income', 'amount', 'comment')
    )

    # Criar mapas separados para receitas e despesas
    income_map = {}
    expenses_map = {}
    
    for t in transactions_qs:
        subcat_id = t['subcategory_id']
        amount = float(t['amount_sum'])
        if t['type'] == Transaction.TYPE_INCOME:
            income_map[subcat_id] = {
                'subcategory_id': subcat_id,
                'subcategory__name': t['subcategory__name'],
                'subcategory__category_id': t['subcategory__category_id'],
                'subcategory__category__name': t['subcategory__category__name'],
                'subcategory__category__is_income': t['subcategory__category__is_income'],
                'amount': amount,
            }
        else:  # TYPE_EXPENSE
            expenses_map[subcat_id] = {
                'subcategory_id': subcat_id,
                'subcategory__name': t['subcategory__name'],
                'subcategory__category_id': t['subcategory__category_id'],
                'subcategory__category__name': t['subcategory__category__name'],
                'subcategory__category__is_income': t['subcategory__category__is_income'],
                'amount': amount,
            }
    
    budgets_map = {b['subcategory_id']: b for b in budgets_qs}

    # No modo edição, incluir TODAS as subcategorias
    # No modo visualização, incluir apenas subcategorias com transações ou orçamentos
    if is_edit_mode:
        # Modo edição: incluir todas as subcategorias
        all_subcategories = Subcategory.objects.select_related('category').all()
        subcategory_ids = set(all_subcategories.values_list('id', flat=True))
    else:
        # Modo visualização: apenas subcategorias com atividade (gasto ou orçado > 0)
        subcategory_ids = set(income_map.keys()) | set(expenses_map.keys()) | set(budgets_map.keys())

    # Agrupar por categoria
    categories_dict = {}
    
    for subcat_id in subcategory_ids:
        income = income_map.get(subcat_id)
        exp = expenses_map.get(subcat_id)
        bud = budgets_map.get(subcat_id)
        
        # Obter informações da categoria e subcategoria
        if income:
            category_id = income['subcategory__category_id']
            category_name = income['subcategory__category__name'] or 'Sem categoria'
            category_is_income = income.get('subcategory__category__is_income', False)
            subcategory_name = income['subcategory__name'] or 'Sem nome'
        elif exp:
            category_id = exp['subcategory__category_id']
            category_name = exp['subcategory__category__name'] or 'Sem categoria'
            category_is_income = exp.get('subcategory__category__is_income', False)
            subcategory_name = exp['subcategory__name'] or 'Sem nome'
        elif bud:
            category_id = bud['subcategory__category_id']
            category_name = bud['subcategory__category__name'] or 'Sem categoria'
            category_is_income = bud.get('subcategory__category__is_income', False)
            subcategory_name = bud['subcategory__name'] or 'Sem nome'
        else:
            try:
                subcategory = Subcategory.objects.select_related('category').get(id=subcat_id)
                category_id = subcategory.category.id
                category_name = subcategory.category.name
                category_is_income = subcategory.category.is_income
                subcategory_name = subcategory.name
            except Subcategory.DoesNotExist:
                continue
        
        # Para receitas, usar o valor da receita; para despesas, usar o valor gasto
        spent = float(income['amount']) if income else (float(exp['amount']) if exp else 0.0)
        # Garantir que budget seja sempre um float, mesmo quando não há orçamento
        if bud:
            budget = float(bud['amount'])
        else:
            budget = 0.0
        
        # Calcular diferença baseado no tipo de categoria
        # Receitas: Recebido - Orçado
        # Despesas: Orçado - Gasto
        if category_is_income:
            diff = spent - budget  # Recebido - Orçado
        else:
            diff = budget - spent  # Orçado - Gasto
        
        percent = (spent / budget * 100) if budget > 0 else None
        
        # Inicializar categoria se não existir
        if category_id not in categories_dict:
            categories_dict[category_id] = {
                'category_id': category_id,
                'category_name': category_name,
                'category_is_income': category_is_income,
                'subcategories': [],
                'total_budget': 0.0,
                'total_spent': 0.0,
            }
        
        # Adicionar subcategoria
        # Para campos input type="number", precisamos garantir que o valor use ponto como separador decimal
        # Criar uma versão string do budget com ponto decimal para uso em inputs
        budget_str = f"{budget:.2f}" if budget else "0.00"
        # Obter comentário do orçamento
        budget_comment = bud.get('comment', '') if bud else ''
        
        categories_dict[category_id]['subcategories'].append({
            'subcategory_id': subcat_id,
            'subcategory_name': subcategory_name,
            'budget': budget,
            'budget_str': budget_str,  # String formatada com ponto decimal para inputs
            'budget_comment': budget_comment,  # Comentário do orçamento
            'spent': spent,
            'diff': diff,
            'percent': percent,
        })
        
        # Acumular totais da categoria
        categories_dict[category_id]['total_budget'] += budget
        categories_dict[category_id]['total_spent'] += spent
    
    # Ordenar categorias: primeiro Receitas (is_income=True), depois Despesas (is_income=False)
    # Dentro de cada grupo, ordenar alfabeticamente
    sorted_categories = sorted(
        categories_dict.values(),
        key=lambda c: (
            not c.get('category_is_income', False),  # False (Receitas) vem primeiro, True (Despesas) vem depois
            (c['category_name'] or 'Sem categoria').lower()
        )
    )
    
    # Ordenar subcategorias dentro de cada categoria alfabeticamente
    for cat in sorted_categories:
        cat['subcategories'].sort(key=lambda s: (s['subcategory_name'] or 'Sem nome').lower())
        # Calcular diferença total baseado no tipo de categoria
        # Receitas: Recebido - Orçado
        # Despesas: Orçado - Gasto
        if cat.get('category_is_income', False):
            cat['total_diff'] = cat['total_spent'] - cat['total_budget']  # Recebido - Orçado
        else:
            cat['total_diff'] = cat['total_budget'] - cat['total_spent']  # Orçado - Gasto
        cat['total_percent'] = (cat['total_spent'] / cat['total_budget'] * 100) if cat['total_budget'] > 0 else None
    
    # No modo visualização, filtrar categorias: mostrar apenas se tiver gasto OU orçado > 0
    if not is_edit_mode:
        filtered_categories = []
        for cat in sorted_categories:
            # Verificar se alguma subcategoria tem gasto ou orçado > 0
            has_activity = False
            for subcat in cat['subcategories']:
                if subcat['spent'] > 0 or subcat['budget'] > 0:
                    has_activity = True
                    break
            if has_activity:
                filtered_categories.append(cat)
        sorted_categories = filtered_categories
    
    # Separar categorias em Receitas e Despesas
    income_categories = [cat for cat in sorted_categories if cat.get('category_is_income', False)]
    expense_categories = [cat for cat in sorted_categories if not cat.get('category_is_income', False)]
    
    # Calcular totais para Receitas
    income_total_budget = sum(cat['total_budget'] for cat in income_categories)
    income_total_spent = sum(cat['total_spent'] for cat in income_categories)
    income_total_diff = sum(cat.get('total_diff', 0) for cat in income_categories)
    income_total_percent = (income_total_spent / income_total_budget * 100) if income_total_budget > 0 else None
    
    # Calcular totais para Despesas
    expense_total_budget = sum(cat['total_budget'] for cat in expense_categories)
    expense_total_spent = sum(cat['total_spent'] for cat in expense_categories)
    expense_total_diff = sum(cat.get('total_diff', 0) for cat in expense_categories)
    expense_total_percent = (expense_total_spent / expense_total_budget * 100) if expense_total_budget > 0 else None
    
    # Calcular totais gerais
    total_budget = income_total_budget + expense_total_budget
    total_spent = income_total_spent + expense_total_spent
    total_diff = income_total_diff + expense_total_diff
    total_percent = (total_spent / total_budget * 100) if total_budget > 0 else None
    
    # Calcular resumo financeiro
    # Saldo atual nas Contas
    from decimal import Decimal
    current_balance = Account.objects.aggregate(
        total=Coalesce(Sum('balance'), Value(0), output_field=DecimalField())
    )['total'] or Decimal('0.00')
    current_balance = float(current_balance)
    
    # Total de Receitas no mês selecionado (incluindo pagas e não pagas)
    total_income = income_total_spent
    
    # Total de Despesas no mês selecionado (incluindo pagas e não pagas)
    total_expenses = expense_total_spent
    
    # Diferença entre Receitas e Despesas
    income_expense_diff = total_income - total_expenses

    # Diferença entre Receitas Orçadas e Despesas Orçadas
    budget_diff = income_total_budget - expense_total_budget
    
    # Calcular receitas e despesas PAGAS para o Saldo Projetado
    paid_income = Transaction.objects.filter(
        payment_date__year=year,
        payment_date__month=month,
        type=Transaction.TYPE_INCOME,
        is_paid=True
    ).aggregate(
        total=Coalesce(Sum('amount'), Value(0), output_field=DecimalField())
    )['total'] or Decimal('0.00')
    paid_income = float(paid_income)
    
    paid_expenses = Transaction.objects.filter(
        payment_date__year=year,
        payment_date__month=month,
        type=Transaction.TYPE_EXPENSE,
        is_paid=True
    ).aggregate(
        total=Coalesce(Sum('amount'), Value(0), output_field=DecimalField())
    )['total'] or Decimal('0.00')
    paid_expenses = float(paid_expenses)
    
    # Saldo projetado = Saldo Atual + Receitas Pagas - Despesas Pagas
    projected_balance = current_balance + paid_income - paid_expenses + budget_diff

    # Buscar todos os templates para o modal
    templates = BudgetTemplate.objects.all().order_by('name')
    
    # Buscar todas as subcategorias agrupadas por categoria para os modais
    all_subcategories = Subcategory.objects.select_related('category').all().order_by('category__name', 'name')
    subcategories_by_category = {}
    for subcat in all_subcategories:
        cat_id = subcat.category.id
        if cat_id not in subcategories_by_category:
            subcategories_by_category[cat_id] = {
                'category_id': cat_id,
                'category_name': subcat.category.name,
                'category_is_income': subcat.category.is_income,
                'subcategories': []
            }
        subcategories_by_category[cat_id]['subcategories'].append({
            'id': subcat.id,
            'name': subcat.name,
        })
    
    # Ordenar categorias: Receitas primeiro, depois Despesas
    sorted_subcategories_by_category = sorted(
        subcategories_by_category.values(),
        key=lambda c: (
            not c.get('category_is_income', False),
            (c['category_name'] or 'Sem categoria').lower()
        )
    )
    
    context = {
        'year': year,
        'month': month,
        'is_edit_mode': is_edit_mode,
        'income_categories': income_categories,
        'expense_categories': expense_categories,
        'income_total_budget': income_total_budget,
        'income_total_spent': income_total_spent,
        'income_total_diff': income_total_diff,
        'income_total_percent': income_total_percent,
        'expense_total_budget': expense_total_budget,
        'expense_total_spent': expense_total_spent,
        'expense_total_diff': expense_total_diff,
        'expense_total_percent': expense_total_percent,
        'total_budget': total_budget,
        'total_spent': total_spent,
        'total_diff': total_diff,
        'total_percent': total_percent,
        'current_balance': current_balance,
        'total_income': total_income,
        'total_expenses': total_expenses,
        'income_expense_diff': income_expense_diff,
        'budget_diff': budget_diff,
        'projected_balance': projected_balance,
        'templates': templates,
        'subcategories_by_category': sorted_subcategories_by_category,
    }
    return render(request, 'finance/report.html', context)


@login_required
def credit_cards_view(request):
    """
    Página para gerenciar cartões de crédito:
    - Listar cartões cadastrados
    - Criar novo cartão
    - Editar cartão existente
    - Deletar cartão
    """
    user = request.user

    if request.method == 'POST':
        action = request.POST.get('action')
        card_id = request.POST.get('card_id')

        if action == 'delete' and card_id:
            try:
                card = CreditCard.objects.get(id=card_id)
                card_name = card.name
                card.delete()
                log_action(
                    user,
                    f"Deletou cartão de crédito: {card_name}",
                    f"ID: {card_id}"
                )
                messages.success(request, f"Cartão '{card_name}' deletado com sucesso.")
            except CreditCard.DoesNotExist:
                messages.error(request, "Cartão não encontrado.")
            return redirect('finance:credit_cards')

        # Criar ou editar cartão
        name = request.POST.get('name', '').strip()
        closing_day_str = request.POST.get('closing_day', '')
        due_day_str = request.POST.get('due_day', '')

        if not name or not closing_day_str or not due_day_str:
            messages.error(request, "Preencha todos os campos obrigatórios.")
            return redirect('finance:credit_cards')

        try:
            closing_day = int(closing_day_str)
            due_day = int(due_day_str)
            if not (1 <= closing_day <= 31) or not (1 <= due_day <= 31):
                raise ValueError("Dia deve estar entre 1 e 31")
        except ValueError:
            messages.error(request, "Dias de fechamento e vencimento devem ser números entre 1 e 31.")
            return redirect('finance:credit_cards')

        if action == 'edit' and card_id:
            try:
                card = CreditCard.objects.get(id=card_id)
                old_name = card.name
                card.name = name
                card.closing_day = closing_day
                card.due_day = due_day
                card.save()
                log_action(
                    user,
                    f"Editou cartão de crédito: {name}",
                    f"ID: {card_id}, Fechamento: dia {closing_day}, Vencimento: dia {due_day}"
                )
                messages.success(request, f"Cartão '{card.name}' atualizado com sucesso.")
            except CreditCard.DoesNotExist:
                messages.error(request, "Cartão não encontrado.")
        else:
            # Criar novo cartão
            CreditCard.objects.create(
                user=user,
                name=name,
                closing_day=closing_day,
                due_day=due_day
            )
            log_action(
                user,
                f"Criou cartão de crédito: {name}",
                f"Fechamento: dia {closing_day}, Vencimento: dia {due_day}"
            )
            messages.success(request, f"Cartão '{name}' criado com sucesso.")

        return redirect('finance:credit_cards')

    # GET
    credit_cards = CreditCard.objects.all().order_by('name')
    editing_card_id = request.GET.get('edit')

    context = {
        'credit_cards': credit_cards,
        'editing_card_id': int(editing_card_id) if editing_card_id and editing_card_id.isdigit() else None,
    }
    return render(request, 'finance/credit_cards.html', context)


@login_required
def all_transactions_view(request):
    """
    Página para listar todos os lançamentos em uma tabela.
    Filtra por mês/ano usando a sessão compartilhada com a página de Relatório.
    Suporta filtros adicionais: tipo, cartão, status, categoria, parcelado.
    """
    # Obter mês/ano da sessão compartilhada (mesma da página de Relatório)
    year, month = _get_year_month_from_request(request, use_session=True, session_key_prefix='shared_')
    
    # Iniciar query com filtro de ano
    transactions = Transaction.objects.filter(
        payment_date__year=year
    ).select_related('subcategory', 'subcategory__category', 'account', 'credit_card')
    
    # Filtrar por mês se não for "Todos" (month != 0)
    if month != 0:
        transactions = transactions.filter(payment_date__month=month)
    
    # Filtros opcionais
    filter_type = request.GET.get('type', '')
    if filter_type in [Transaction.TYPE_INCOME, Transaction.TYPE_EXPENSE]:
        transactions = transactions.filter(type=filter_type)
    
    filter_credit_card = request.GET.get('credit_card', '')
    if filter_credit_card:
        if filter_credit_card == 'debit':
            # Filtrar apenas lançamentos sem cartão de crédito (débito)
            transactions = transactions.filter(credit_card__isnull=True)
        else:
            try:
                card_id = int(filter_credit_card)
                transactions = transactions.filter(credit_card_id=card_id)
            except ValueError:
                pass
    
    filter_status = request.GET.get('status', '')
    if filter_status == 'paid':
        # Apenas pagas: sem cartão OU com cartão e is_paid=True
        transactions = transactions.filter(
            Q(credit_card__isnull=True) | Q(credit_card__isnull=False, is_paid=True)
        )
    elif filter_status == 'pending':
        # Apenas pendentes: com cartão e is_paid=False
        transactions = transactions.filter(credit_card__isnull=False, is_paid=False)
    
    filter_subcategory = request.GET.get('subcategory', '')
    if filter_subcategory:
        try:
            subcat_id = int(filter_subcategory)
            transactions = transactions.filter(subcategory_id=subcat_id)
        except ValueError:
            pass
    
    filter_installment = request.GET.get('installment', '')
    if filter_installment == 'yes':
        transactions = transactions.filter(is_installment=True)
    elif filter_installment == 'no':
        transactions = transactions.filter(is_installment=False)
    
    filter_owner_tag = request.GET.get('owner_tag', '')
    if filter_owner_tag in [Transaction.OWNER_THI, Transaction.OWNER_THA]:
        transactions = transactions.filter(owner_tag=filter_owner_tag)
    
    # Ordenar pelo dia de lançamento (mais recentes primeiro)
    transactions = transactions.order_by('-date', '-id')
    
    # Paginação: 100 itens por página
    paginator = Paginator(transactions, 100)
    page_number = request.GET.get('page', 1)
    transactions_page = paginator.get_page(page_number)
    
    # Buscar dados para os filtros
    credit_cards = CreditCard.objects.all().order_by('name')
    subcategories = Subcategory.objects.select_related('category').all().order_by('category__name', 'name')
    
    # Construir URL de retorno com todos os filtros (para redirecionamento após edição)
    from urllib.parse import urlencode, quote
    filter_params = {
        'year': str(year),
        'month': str(month),
    }
    if filter_type:
        filter_params['type'] = filter_type
    if filter_credit_card:
        filter_params['credit_card'] = filter_credit_card
    if filter_status:
        filter_params['status'] = filter_status
    if filter_subcategory:
        filter_params['subcategory'] = filter_subcategory
    if filter_installment:
        filter_params['installment'] = filter_installment
    if filter_owner_tag:
        filter_params['owner_tag'] = filter_owner_tag
    
    # Construir URL completa e codificar para uso como parâmetro next
    base_url = reverse('finance:all_transactions')
    query_string = urlencode(filter_params)
    full_url = f"{base_url}?{query_string}"
    # Codificar a URL completa para passar como parâmetro
    return_url = quote(full_url, safe='')
    
    # Para uso no template (sem codificar)
    return_url_plain = f"{base_url}?{query_string}"
    
    # Construir query string base para paginação (sem page)
    pagination_base_query = query_string
    
    context = {
        'transactions': transactions_page,
        'pagination_base_query': pagination_base_query,
        'year': year,
        'month': month,
        'credit_cards': credit_cards,
        'subcategories': subcategories,
        'filter_type': filter_type,
        'filter_credit_card': filter_credit_card,
        'filter_status': filter_status,
        'filter_subcategory': filter_subcategory,
        'filter_installment': filter_installment,
        'filter_owner_tag': filter_owner_tag,
        'return_url': return_url,
        'return_url_plain': return_url_plain,
    }
    return render(request, 'finance/all_transactions.html', context)


@login_required
def all_logs_view(request):
    """
    Página para listar todos os logs de ações em uma tabela.
    """
    # Buscar todos os logs ordenados por data (mais recentes primeiro)
    logs_list = ActionLog.objects.all().select_related('user').order_by('-timestamp')
    
    # Paginação: 50 itens por página
    paginator = Paginator(logs_list, 50)
    page_number = request.GET.get('page', 1)
    logs = paginator.get_page(page_number)
    
    context = {
        'logs': logs,
    }
    return render(request, 'finance/all_logs.html', context)


@login_required
def dashboard_view(request):
    """
    Dashboard com visão geral do sistema financeiro.
    Permite filtrar por mês/ano.
    """
    user = request.user
    
    # Obter ano/mês dos parâmetros GET ou usar sessão/padrão
    year, month = _get_year_month_from_request(request, use_session=True, session_key_prefix='dashboard_')
    
    # Saldo total das contas (sempre atual, não depende do filtro de mês)
    accounts = Account.objects.all()
    total_balance = accounts.aggregate(
        total=Coalesce(Sum('balance'), Value(0), output_field=DecimalField())
    )['total']
    
    # Receitas e despesas do mês selecionado
    month_income = Transaction.objects.filter(
        payment_date__year=year,
        payment_date__month=month,
        type=Transaction.TYPE_INCOME
    ).aggregate(
        total=Coalesce(Sum('amount'), Value(0), output_field=DecimalField())
    )['total']
    
    month_expenses = Transaction.objects.filter(
        payment_date__year=year,
        payment_date__month=month,
        type=Transaction.TYPE_EXPENSE
    ).aggregate(
        total=Coalesce(Sum('amount'), Value(0), output_field=DecimalField())
    )['total']
    
    month_balance = month_income - month_expenses
    
    # Quantidade de transações no mês selecionado
    month_transactions_count = Transaction.objects.filter(
        payment_date__year=year,
        payment_date__month=month
    ).count()
    
    # Média diária de gastos (despesas do mês / número de dias no mês)
    # Usar o número de dias do mês selecionado
    days_in_month = calendar.monthrange(year, month)[1]
    if days_in_month > 0:
        daily_average = month_expenses / Decimal(days_in_month)
    else:
        daily_average = Decimal('0')
    
    # Calcular orçamentos do mês
    budgets_qs = MonthlyBudget.objects.filter(
        year=year,
        month=month
    ).select_related('subcategory', 'subcategory__category').values(
        'subcategory__category__is_income',
        'amount'
    )
    
    income_budget = Decimal('0')
    expense_budget = Decimal('0')
    
    for budget in budgets_qs:
        if budget['subcategory__category__is_income']:
            income_budget += budget['amount']
        else:
            expense_budget += budget['amount']
    
    # Saldo Planejado (Receitas Orçadas - Despesas Orçadas)
    budget_diff = income_budget - expense_budget
    
    # Calcular receitas e despesas PAGAS para o Saldo Projetado
    paid_income = Transaction.objects.filter(
        payment_date__year=year,
        payment_date__month=month,
        type=Transaction.TYPE_INCOME,
        is_paid=True
    ).aggregate(
        total=Coalesce(Sum('amount'), Value(0), output_field=DecimalField())
    )['total'] or Decimal('0')
    
    paid_expenses = Transaction.objects.filter(
        payment_date__year=year,
        payment_date__month=month,
        type=Transaction.TYPE_EXPENSE,
        is_paid=True
    ).aggregate(
        total=Coalesce(Sum('amount'), Value(0), output_field=DecimalField())
    )['total'] or Decimal('0')
    
    # Saldo Projetado = Saldo Atual + Receitas Pagas - Despesas Pagas + Saldo Planejado
    projected_balance = total_balance + paid_income - paid_expenses + budget_diff
    
    # Percentuais de planejamento
    income_planned_percent = (float(month_income) / float(income_budget) * 100) if income_budget > 0 else 0
    expense_planned_percent = (float(month_expenses) / float(expense_budget) * 100) if expense_budget > 0 else 0
    
    # Todas as faturas do mês selecionado (pagas e pendentes)
    credit_cards = CreditCard.objects.all().order_by('name')
    all_invoices = []
    
    for card in credit_cards:
        # Buscar todas as transações do cartão no mês selecionado
        card_transactions = Transaction.objects.filter(
            credit_card=card,
            payment_date__year=year,
            payment_date__month=month,
            type=Transaction.TYPE_EXPENSE
        )
        
        total_transactions = card_transactions.aggregate(
            total=Coalesce(Sum('amount'), Value(0), output_field=DecimalField())
        )['total']
        
        # Verificar se todas estão pagas
        unpaid_count = card_transactions.filter(is_paid=False).count()
        total_count = card_transactions.count()
        
        if total_transactions > 0:
            all_invoices.append({
                'card_name': card.name,
                'year': year,
                'month': month,
                'total': total_transactions,
                'is_paid': unpaid_count == 0,  # True se todas estão pagas
                'unpaid_count': unpaid_count,
                'total_count': total_count
            })
    
    # Últimas 10 transações do mês selecionado
    recent_transactions = Transaction.objects.filter(
        payment_date__year=year,
        payment_date__month=month
    ).select_related('subcategory', 'subcategory__category', 'account', 'credit_card')\
        .order_by('-date', '-id')[:10]
    
    # Dados para o gráfico: subcategorias com valores gastos e orçados
    subcategories_chart_data = []
    
    # Buscar todas as subcategorias
    exp_subcategories = Subcategory.objects.select_related('category').filter(
        category__is_income=False  #Somente Despesas
    ).order_by('category__name', 'name')
    
    for subcat in exp_subcategories:
        # Valor gasto/recebido no mês
        spent = Transaction.objects.filter(
            payment_date__year=year,
            payment_date__month=month,
            subcategory=subcat
        ).aggregate(
            total=Coalesce(Sum('amount'), Value(0), output_field=DecimalField())
        )['total'] or Decimal('0')
        
        # Valor orçado
        budget = MonthlyBudget.objects.filter(
            year=year,
            month=month,
            subcategory=subcat
        ).aggregate(
            total=Coalesce(Sum('amount'), Value(0), output_field=DecimalField())
        )['total'] or Decimal('0')
        
        # Só incluir se tiver gasto ou orçado
        if spent > 0 or budget > 0:
            subcategories_chart_data.append({
                'name': f"{subcat.category.name} - {subcat.name}",
                'spent': float(spent),
                'budget': float(budget),
            })
    
    context = {
        'year': year,
        'month': month,
        'total_balance': total_balance,
        'month_income': month_income,
        'month_expenses': month_expenses,
        'month_balance': month_balance,
        'month_transactions_count': month_transactions_count,
        'daily_average': daily_average,
        'projected_balance': projected_balance,
        'all_invoices': all_invoices,
        'recent_transactions': recent_transactions,
        'income_planned_percent': income_planned_percent,
        'expense_planned_percent': expense_planned_percent, 
        'budget_diff': budget_diff,
        'income_budget': income_budget,
        'expense_budget': expense_budget,
        'subcategories_chart_data': json.dumps(subcategories_chart_data),
    }
    return render(request, 'finance/dashboard.html', context)


@login_required
def budget_template_list_view(request):
    """Lista todos os templates de orçamento (globais)."""
    from django.http import JsonResponse
    
    templates = BudgetTemplate.objects.all().order_by('name')
    templates_data = []
    
    for template in templates:
        templates_data.append({
            'id': template.id,
            'name': template.name,
            'description': template.description or '',
            'created_at': template.created_at.strftime('%d/%m/%Y %H:%M'),
            'updated_at': template.updated_at.strftime('%d/%m/%Y %H:%M'),
            'item_count': template.items.count(),
        })
    
    return JsonResponse({'templates': templates_data})


@login_required
def budget_template_create_view(request):
    """Cria um novo template de orçamento."""
    from django.http import JsonResponse
    
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Método não permitido'}, status=405)
    
    try:
        if request.content_type and 'application/json' in request.content_type:
            data = json.loads(request.body)
        else:
            data = request.POST
        
        name = data.get('name', '').strip()
        if not name:
            return JsonResponse({'success': False, 'error': 'Nome do template é obrigatório'}, status=400)
        
        description = data.get('description', '').strip() or None
        items_data = data.get('items', [])  # Lista de {subcategory_id, amount}
        
        # Criar template
        template = BudgetTemplate.objects.create(
            name=name,
            description=description,
            user=request.user
        )
        
        # Criar itens do template
        for item_data in items_data:
            subcategory_id = item_data.get('subcategory_id')
            amount_str = item_data.get('amount', '0').strip()
            comment_str = item_data.get('comment', '').strip() or None
            
            if not subcategory_id or not amount_str:
                continue
            
            try:
                amount = Decimal(amount_str.replace(',', '.'))
                if amount > 0:
                    BudgetTemplateItem.objects.create(
                        template=template,
                        subcategory_id=subcategory_id,
                        amount=amount,
                        comment=comment_str
                    )
            except (ValueError, Subcategory.DoesNotExist):
                continue
        
        log_action(
            request.user,
            f"Criou template de orçamento: {template.name}",
            f"Template ID: {template.id}, Itens: {template.items.count()}"
        )
        
        return JsonResponse({
            'success': True,
            'template_id': template.id,
            'message': 'Template criado com sucesso'
        })
    
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)


@login_required
def budget_template_edit_view(request, template_id):
    """Edita um template de orçamento existente."""
    from django.http import JsonResponse
    
    try:
        template = BudgetTemplate.objects.get(id=template_id)
    except BudgetTemplate.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Template não encontrado'}, status=404)
    
    if request.method == 'GET':
        # Retornar dados do template
        items_data = []
        for item in template.items.select_related('subcategory', 'subcategory__category').all():
            items_data.append({
                'subcategory_id': item.subcategory.id,
                'subcategory_name': str(item.subcategory),
                'amount': str(item.amount),
                'comment': item.comment or ''
            })
        
        return JsonResponse({
            'id': template.id,
            'name': template.name,
            'description': template.description or '',
            'items': items_data
        })
    
    elif request.method == 'POST':
        try:
            data = json.loads(request.body) if request.content_type == 'application/json' else request.POST
            
            name = data.get('name', '').strip()
            if not name:
                return JsonResponse({'success': False, 'error': 'Nome do template é obrigatório'}, status=400)
            
            description = data.get('description', '').strip() or None
            items_data = data.get('items', [])
            
            # Atualizar template
            template.name = name
            template.description = description
            template.save()
            
            # Deletar itens antigos e criar novos
            template.items.all().delete()
            
            for item_data in items_data:
                subcategory_id = item_data.get('subcategory_id')
                amount_str = item_data.get('amount', '0').strip()
                comment_str = item_data.get('comment', '').strip() or None
                
                if not subcategory_id or not amount_str:
                    continue
                
                try:
                    amount = Decimal(amount_str.replace(',', '.'))
                    if amount > 0:
                        BudgetTemplateItem.objects.create(
                            template=template,
                            subcategory_id=subcategory_id,
                            amount=amount,
                            comment=comment_str
                        )
                except (ValueError, Subcategory.DoesNotExist):
                    continue
            
            log_action(
                request.user,
                f"Editou template de orçamento: {template.name}",
                f"Template ID: {template.id}, Itens: {template.items.count()}"
            )
            
            return JsonResponse({
                'success': True,
                'message': 'Template atualizado com sucesso'
            })
        
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)}, status=400)
    
    return JsonResponse({'success': False, 'error': 'Método não permitido'}, status=405)


@login_required
def budget_template_delete_view(request, template_id):
    """Deleta um template de orçamento."""
    from django.http import JsonResponse
    
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Método não permitido'}, status=405)
    
    try:
        template = BudgetTemplate.objects.get(id=template_id)
        template_name = template.name
        template.delete()
        
        log_action(
            request.user,
            f"Deletou template de orçamento: {template_name}",
            f"Template ID: {template_id}"
        )
        
        return JsonResponse({
            'success': True,
            'message': 'Template deletado com sucesso'
        })
    
    except BudgetTemplate.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Template não encontrado'}, status=404)
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)


@login_required
def budget_template_apply_view(request):
    """Aplica um template de orçamento ao mês/ano selecionado."""
    from django.http import JsonResponse
    
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Método não permitido'}, status=405)
    
    try:
        if request.content_type and 'application/json' in request.content_type:
            data = json.loads(request.body)
        else:
            data = request.POST
        
        template_id = data.get('template_id')
        year = int(data.get('year'))
        month = int(data.get('month'))
        replace_mode = data.get('replace_mode', 'empty')  # 'all' ou 'empty'
        
        if not template_id:
            return JsonResponse({'success': False, 'error': 'Template ID é obrigatório'}, status=400)
        
        template = BudgetTemplate.objects.get(id=template_id)
        items = template.items.select_related('subcategory').all()
        
        applied_count = 0
        skipped_count = 0
        
        for item in items:
            # Verificar se já existe orçamento para esta subcategoria
            existing_budget = MonthlyBudget.objects.filter(
                subcategory=item.subcategory,
                year=year,
                month=month
            ).first()
            
            if replace_mode == 'empty' and existing_budget:
                # Modo "preencher vazios": pular se já existe
                skipped_count += 1
                continue
            
            # Criar ou atualizar orçamento
            MonthlyBudget.objects.update_or_create(
                user=request.user,
                subcategory=item.subcategory,
                year=year,
                month=month,
                defaults={
                    'amount': item.amount,
                    'comment': item.comment
                }
            )
            applied_count += 1
        
        log_action(
            request.user,
            f"Aplicou template de orçamento: {template.name}",
            f"Template ID: {template.id}, Mês/Ano: {month:02d}/{year}, Modo: {replace_mode}, Aplicados: {applied_count}, Ignorados: {skipped_count}"
        )
        
        return JsonResponse({
            'success': True,
            'message': f'Template aplicado com sucesso. {applied_count} orçamentos criados/atualizados.',
            'applied_count': applied_count,
            'skipped_count': skipped_count
        })
    
    except BudgetTemplate.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Template não encontrado'}, status=404)
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)


@login_required
def budget_template_save_current_view(request):
    """Salva o orçamento atual (do mês/ano selecionado) como um novo template."""
    from django.http import JsonResponse
    
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Método não permitido'}, status=405)
    
    try:
        if request.content_type and 'application/json' in request.content_type:
            data = json.loads(request.body)
        else:
            data = request.POST
        
        name = data.get('name', '').strip()
        if not name:
            return JsonResponse({'success': False, 'error': 'Nome do template é obrigatório'}, status=400)
        
        description = data.get('description', '').strip() or None
        year = int(data.get('year'))
        month = int(data.get('month'))
        
        # Buscar orçamentos do mês/ano
        budgets = MonthlyBudget.objects.filter(
            year=year,
            month=month
        ).select_related('subcategory')
        
        if not budgets.exists():
            return JsonResponse({'success': False, 'error': 'Não há orçamentos para este mês/ano'}, status=400)
        
        # Criar template
        template = BudgetTemplate.objects.create(
            name=name,
            description=description,
            user=request.user
        )
        
        # Criar itens do template baseados nos orçamentos
        for budget in budgets:
            BudgetTemplateItem.objects.create(
                template=template,
                subcategory=budget.subcategory,
                amount=budget.amount,
                comment=budget.comment
            )
        
        log_action(
            request.user,
            f"Salvou orçamento como template: {template.name}",
            f"Template ID: {template.id}, Mês/Ano: {month:02d}/{year}, Itens: {template.items.count()}"
        )
        
        return JsonResponse({
            'success': True,
            'template_id': template.id,
            'message': f'Template criado com sucesso com {template.items.count()} itens'
        })
    
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)
