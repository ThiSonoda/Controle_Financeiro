# finance/views.py
from datetime import date
import calendar
import uuid

from django.contrib.auth.decorators import login_required
from django.db.models import Sum, Value, DecimalField
from django.db.models.functions import Coalesce
from django.shortcuts import render, redirect
from django.urls import reverse
from django.contrib import messages

from .models import Category, Subcategory, Account, Transaction, MonthlyBudget, CreditCard, ActionLog


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


def _get_year_month_from_request(request):
    """Lê year/month do GET, com default para mês atual."""
    today = date.today()
    try:
        year = int(request.GET.get('year', today.year))
    except ValueError:
        year = today.year
    try:
        month = int(request.GET.get('month', today.month))
    except ValueError:
        month = today.month
    return year, month

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

        # CAMPOS PARA PARCELAMENTO
        is_installment = request.POST.get('is_installment') == 'on'
        installments_str = request.POST.get('installments') or '1'
        
        # CAMPO PARA CARTÃO DE CRÉDITO
        credit_card_id = request.POST.get('credit_card', '').strip()

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
            account = Account.objects.get(id=1)
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

        from decimal import Decimal, ROUND_HALF_UP

        if is_installment and installments > 1:
            # Gera um ID único para o grupo de parcelas
            group_id = uuid.uuid4()

            # Valor informado será considerado o TOTAL da compra
            # Calculamos o valor de cada parcela (ajustando a última pelo arredondamento)
            base_parcela = (amount / installments).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            valores = [base_parcela for _ in range(installments)]
            diferenca = amount - sum(valores)
            # Compensa diferença na última parcela (quando a divisão não é exata em centavos)
            valores[-1] += diferenca

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
                    installment_group=group_id,
                    credit_card=credit_card,
                    is_paid=is_paid_value,
                )
                created_transaction_ids.append(transaction.id)

            messages.success(request, f"Compra parcelada lançada em {installments} parcelas.")
            # Registrar log
            log_action(
                user,
                f"Criou compra parcelada: {description or 'Sem descrição'} ({installments} parcelas de R$ {valores[0]:.2f})",
                f"ID do grupo: {group_id}, Total: R$ {amount:.2f}, Subcategoria: {subcategory.name}, Conta: {account.name}"
            )
            # Redireciona com os IDs das transações criadas
            ids_param = ','.join(map(str, created_transaction_ids))
            return redirect(f"{reverse('finance:transactions')}?highlight={ids_param}")
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
                credit_card=credit_card,
                is_paid=is_paid_value,
            )
            messages.success(request, "Lançamento salvo com sucesso.")
            # Registrar log
            log_action(
                user,
                f"Criou lançamento: {description or 'Sem descrição'} ({transaction.get_type_display()})",
                f"Valor: R$ {amount:.2f}, Data: {t_date}, Subcategoria: {subcategory.name}, Conta: {account.name}"
            )
            # Redireciona com o ID da transação criada
            return redirect(f"{reverse('finance:transactions')}?highlight={transaction.id}")

    # GET
    subcategories = Subcategory.objects.all().select_related('category').order_by('category__name', 'name')
    accounts = Account.objects.all().order_by('name')
    credit_cards = CreditCard.objects.all().order_by('name')

    transactions = (
        Transaction.objects
        .all()
        .select_related('subcategory', 'subcategory__category', 'account', 'credit_card')
        .order_by('-date', '-id')[:50]  # últimos 50
    )
    
    # Obter mês/ano para exibição (default: mês atual)
    year, month = _get_year_month_from_request(request)
    
    # Calcular faturas dos cartões de crédito
    credit_card_invoices = calculate_credit_card_invoices(user, year, month)

    context = {
        'subcategories': subcategories,
        'accounts': accounts,
        'credit_cards': credit_cards,
        'transactions': transactions,
        'credit_card_invoices': credit_card_invoices,
        'selected_year': year,
        'selected_month': month,
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
        log_action(
            user,
            f"Deletou lançamento: {transaction.description or 'Sem descrição'}",
            f"ID: {transaction_id}, Valor: R$ {transaction.amount:.2f}, Tipo: {transaction.get_type_display()}, Data: {transaction.date}"
        )
        transaction.delete()
        messages.success(request, "Lançamento deletado com sucesso.")
    except Transaction.DoesNotExist:
        messages.error(request, "Lançamento não encontrado.")
    
    return redirect('finance:transactions')


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
        credit_card_id = request.POST.get('credit_card', '').strip()
        
        # Validações
        if not date_str or not amount_str or not type_ or not subcategory_id or not account_id:
            messages.error(request, "Preencha todos os campos obrigatórios.")
            return redirect('finance:edit_transaction', transaction_id=transaction_id)
        
        try:
            from datetime import datetime
            t_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            messages.error(request, "Data inválida.")
            return redirect('finance:edit_transaction', transaction_id=transaction_id)
        
        try:
            from decimal import Decimal
            amount = Decimal(amount_str.replace(',', '.'))
        except Exception:
            messages.error(request, "Valor inválido.")
            return redirect('finance:edit_transaction', transaction_id=transaction_id)
        
        try:
            subcategory = Subcategory.objects.get(id=subcategory_id)
            account = Account.objects.get(id=account_id)
        except (Subcategory.DoesNotExist, Account.DoesNotExist):
            messages.error(request, "Subcategoria ou conta não encontrada.")
            return redirect('finance:edit_transaction', transaction_id=transaction_id)
        
        # Buscar cartão de crédito se informado
        credit_card = None
        if credit_card_id:
            try:
                credit_card = CreditCard.objects.get(id=credit_card_id)
            except CreditCard.DoesNotExist:
                messages.error(request, "Cartão de crédito não encontrado.")
                return redirect('finance:edit_transaction', transaction_id=transaction_id)
        
        # Atualizar transação
        transaction.date = t_date
        transaction.amount = amount
        transaction.type = type_
        transaction.subcategory = subcategory
        # A categoria será atualizada automaticamente através do método save() do model
        transaction.account = account
        transaction.description = description
        
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
        log_action(
            user,
            f"Editou lançamento: {description or 'Sem descrição'}",
            f"ID: {transaction_id}, Valor: R$ {amount:.2f}, Tipo: {type_}, Data: {t_date}, Subcategoria: {subcategory.name}"
        )
        messages.success(request, "Lançamento atualizado com sucesso.")
        return redirect('finance:transactions')
    
    # GET - mostrar formulário de edição
    subcategories = Subcategory.objects.all().select_related('category').order_by('category__name', 'name')
    accounts = Account.objects.all().order_by('name')
    credit_cards = CreditCard.objects.all().order_by('name')
    
    context = {
        'transaction': transaction,
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
    year, month = _get_year_month_from_request(request)
    subcategories = Subcategory.objects.all().order_by('name')
    budgets = MonthlyBudget.objects.filter(year=year, month=month)

    budget_map = {b.subcategory_id: b for b in budgets}

    context = {
        'year': year,
        'month': month,
        'subcategories': subcategories,
        'budget_map': budget_map,
    }
    return render(request, 'finance/budget.html', context)


@login_required
def report_view(request):
    """
    Página de relatório: Gasto x Orçado por subcategoria no mês.
    """
    user = request.user
    year, month = _get_year_month_from_request(request)

    # Despesas por categoria (somente TYPE_EXPENSE)
    expenses_qs = (
        Transaction.objects
        .filter(
            date__year=year,
            date__month=month,
            type=Transaction.TYPE_EXPENSE,
        )
        .values('subcategory_id', 'subcategory__name')
        .annotate(spent=Coalesce(Sum('amount'), Value(0), output_field=DecimalField(max_digits=14, decimal_places=2)))
    )

    budgets_qs = (
        MonthlyBudget.objects
        .filter(year=year, month=month)
        .values('subcategory_id', 'subcategory__name', 'amount')
    )

    expenses_map = {e['subcategory_id']: e for e in expenses_qs}
    budgets_map = {b['subcategory_id']: b for b in budgets_qs}

    subcategory_ids = set(expenses_map.keys()) | set(budgets_map.keys())

    report_rows = []
    total_budget = 0
    total_spent = 0

    for cid in subcategory_ids: #cid é o ID da subcategoria
        exp = expenses_map.get(cid)
        bud = budgets_map.get(cid)

        try:
            subcategory = Subcategory.objects.get(id=cid)
            name = subcategory.name
        except Subcategory.DoesNotExist:
            name = 'Sem nome'
        
        spent = float(exp['spent']) if exp else 0.0
        budget = float(bud['amount']) if bud else 0.0
        diff = budget - spent
        percent = (spent / budget * 100) if budget > 0 else None

        total_budget += budget
        total_spent += spent

        report_rows.append({
            'subcategory_id': cid,
            'subcategory_name': name, #or 'Sem nome',  # Garante que nunca seja None
            'budget': budget,
            'spent': spent,
            'diff': diff,
            'percent': percent,
        })

    total_diff = total_budget - total_spent
    total_percent = (total_spent / total_budget * 100) if total_budget > 0 else None

    context = {
        'year': year,
        'month': month,
        'rows': sorted(report_rows, key=lambda r: (r.get('subcategory_name') or 'Sem nome').lower()),
        'total_budget': total_budget,
        'total_spent': total_spent,
        'total_diff': total_diff,
        'total_percent': total_percent,
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
