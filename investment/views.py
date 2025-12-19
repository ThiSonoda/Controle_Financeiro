from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import F, Sum, Q
from django.db import transaction as db_transaction
from decimal import Decimal
from .models import Broker, InvestmentType, Investment, InvestmentTransaction, PendingInvestment
from finance.models import Account, ActionLog


def log_action(user, action, details=''):
    """Registra uma ação do usuário no log."""
    ActionLog.objects.create(
        user=user,
        action=action,
        details=details
    )


@login_required
def investments_view(request):
    """View principal para gerenciamento de investimentos."""
    
    if request.method == 'GET':
        # Listar todos os investimentos
        investments = Investment.objects.all().order_by('broker__name', 'name')
        
        # Calcular saldo total pendente disponível
        total_pending_result = PendingInvestment.objects.aggregate(
            total=Sum(F('amount') - F('amount_allocated'))
        )
        total_pending = total_pending_result['total'] or Decimal('0.00')
        
        # Calcular totais
        investments_active = investments.filter(status='ativo')
        total_invested = investments_active.aggregate(
            total=Sum('current_balance')
        )['total'] or Decimal('0.00')
        
        total_contributed = investments.aggregate(
            total=Sum('total_contributed')
        )['total'] or Decimal('0.00')
        
        global_return = total_invested - total_contributed
        global_return_percentage = (global_return / total_contributed * 100) if total_contributed > 0 else Decimal('0.00')
        
        # Preparar investimentos com cálculos
        investments_list = []
        for inv in investments:
            investments_list.append({
                'id': inv.id,
                'broker': inv.broker.name,
                'broker_id': inv.broker.id,
                'investment_type': inv.investment_type.name,
                'investment_type_id': inv.investment_type.id,
                'name': inv.name,
                'status': inv.status,
                'status_display': inv.get_status_display(),
                'current_balance': inv.current_balance,
                'total_contributed': inv.total_contributed,
                'return_amount': inv.get_return_amount(),
                'return_percentage': inv.get_return_percentage(),
            })
        
        context = {
            'investments': investments_list,
            'total_pending': total_pending,
            'total_invested': total_invested,
            'total_contributed': total_contributed,
            'global_return': global_return,
            'global_return_percentage': global_return_percentage,
            'brokers': Broker.objects.all().order_by('name'),
            'investment_types': InvestmentType.objects.all().order_by('name'),
            'accounts': Account.objects.all().order_by('name'),
        }
        
        return render(request, 'investment/investments.html', context)
    
    elif request.method == 'POST':
        action = request.POST.get('action')
        
        if action == 'allocate_pending':
            amount = Decimal(request.POST.get('amount', '0'))
            broker_id = request.POST.get('broker_id')
            investment_type_id = request.POST.get('investment_type_id')
            name = request.POST.get('name', '').strip()
            transaction_date = request.POST.get('transaction_date')
            investment_id = request.POST.get('investment_select')
            
            # Calcular saldo disponível
            total_pending_result = PendingInvestment.objects.aggregate(
                total=Sum(F('amount') - F('amount_allocated'))
            )
            total_pending = total_pending_result['total'] or Decimal('0.00')
            
            if amount <= 0:
                messages.error(request, "O valor a ser alocado deve ser maior que zero.")
                return redirect('investment:investments')
            
            if amount > total_pending:
                messages.error(request, f"O valor a ser alocado (R$ {amount:.2f}) excede o saldo pendente disponível (R$ {total_pending:.2f}).")
                return redirect('investment:investments')
            
            try:
                with db_transaction.atomic():
                    # Buscar ou criar investimento
                    if investment_id:
                        investment = Investment.objects.get(id=investment_id)
                    else:
                        if not broker_id or not investment_type_id or not name:
                            messages.error(request, "Para criar um novo investimento, é necessário informar corretora, tipo e nome.")
                            return redirect('investment:investments')
                        
                        broker = Broker.objects.get(id=broker_id)
                        investment_type = InvestmentType.objects.get(id=investment_type_id)
                        
                        # Verificar se já existe
                        existing = Investment.objects.filter(broker=broker, name=name).first()
                        if existing:
                            messages.error(request, f"Já existe um investimento com a corretora '{broker.name}' e nome '{name}'.")
                            return redirect('investment:investments')
                        
                        investment = Investment.objects.create(
                            broker=broker,
                            investment_type=investment_type,
                            name=name,
                            status='ativo',
                            current_balance=Decimal('0.00'),
                            total_contributed=Decimal('0.00'),
                        )
                        messages.success(request, f"Novo investimento '{investment.name}' criado com sucesso.")
                    
                    # Distribuir alocação usando FIFO
                    amount_to_allocate = amount
                    pending_investments = PendingInvestment.objects.filter(
                        amount_allocated__lt=F('amount')
                    ).order_by('created_at')
                    
                    for pending_inv in pending_investments:
                        if amount_to_allocate <= 0:
                            break
                        
                        available = pending_inv.amount - pending_inv.amount_allocated
                        
                        if amount_to_allocate <= available:
                            PendingInvestment.objects.filter(id=pending_inv.id).update(
                                amount_allocated=F('amount_allocated') + amount_to_allocate
                            )
                            amount_to_allocate = Decimal('0.00')
                        else:
                            PendingInvestment.objects.filter(id=pending_inv.id).update(
                                amount_allocated=F('amount')
                            )
                            amount_to_allocate -= available
                    
                    # Criar InvestmentTransaction
                    InvestmentTransaction.objects.create(
                        investment=investment,
                        amount=amount,
                        transaction_date=transaction_date,
                        is_contribution=True,
                        is_redemption=False,
                    )
                    
                    # Atualizar Investment
                    investment.total_contributed += amount
                    investment.current_balance += amount
                    investment.save()
                    
                    log_action(
                        request.user,
                        f"Alocação de R$ {amount:.2f} para investimento {investment.name}",
                        f"Investimento ID: {investment.id}, Corretora: {investment.broker.name}, Tipo: {investment.investment_type.name}, Data: {transaction_date}"
                    )
                    messages.success(request, f"Alocação de R$ {amount:.2f} realizada com sucesso para o investimento {investment.name}.")
                    
            except Broker.DoesNotExist:
                messages.error(request, "Corretora não encontrada.")
            except InvestmentType.DoesNotExist:
                messages.error(request, "Tipo de investimento não encontrado.")
            except Investment.DoesNotExist:
                messages.error(request, "Investimento não encontrado.")
            except Exception as e:
                messages.error(request, f"Erro ao realizar alocação: {str(e)}")
            
            return redirect('investment:investments')
        
        elif action == 'update_balance':
            investment_id = request.POST.get('investment_id')
            new_balance = Decimal(request.POST.get('new_balance', '0'))
            transaction_date = request.POST.get('transaction_date')
            
            if new_balance < 0:
                messages.error(request, "O saldo não pode ser negativo.")
                return redirect('investment:investments')
            
            try:
                investment = Investment.objects.get(id=investment_id)
                old_balance = investment.current_balance
                diff = new_balance - old_balance
                
                InvestmentTransaction.objects.create(
                    investment=investment,
                    amount=diff,
                    transaction_date=transaction_date,
                    is_contribution=False,
                    is_redemption=False,
                )
                
                investment.current_balance = new_balance
                investment.save()
                
                log_action(
                    request.user,
                    f"Saldo atualizado do investimento {investment.name}",
                    f"Investimento ID: {investment.id}, Saldo anterior: R$ {old_balance:.2f}, Novo saldo: R$ {new_balance:.2f}, Diferença: R$ {diff:.2f}, Data: {transaction_date}"
                )
                messages.success(request, f"Saldo do investimento {investment.name} atualizado para R$ {new_balance:.2f}.")
                
            except Investment.DoesNotExist:
                messages.error(request, "Investimento não encontrado.")
            except Exception as e:
                messages.error(request, f"Erro ao atualizar saldo: {str(e)}")
            
            return redirect('investment:investments')
        
        elif action == 'add_contribution':
            investment_id = request.POST.get('investment_id')
            amount = Decimal(request.POST.get('amount', '0'))
            transaction_date = request.POST.get('transaction_date')
            
            # Calcular saldo disponível
            total_pending_result = PendingInvestment.objects.aggregate(
                total=Sum(F('amount') - F('amount_allocated'))
            )
            total_pending = total_pending_result['total'] or Decimal('0.00')
            
            if amount <= 0:
                messages.error(request, "O valor a ser aportado deve ser maior que zero.")
                return redirect('investment:investments')
            
            if amount > total_pending:
                messages.error(request, f"O valor a ser aportado (R$ {amount:.2f}) excede o saldo pendente disponível (R$ {total_pending:.2f}).")
                return redirect('investment:investments')
            
            try:
                with db_transaction.atomic():
                    investment = Investment.objects.get(id=investment_id)
                    
                    # Distribuir alocação usando FIFO (mesmo algoritmo de allocate_pending)
                    amount_to_allocate = amount
                    pending_investments = PendingInvestment.objects.filter(
                        amount_allocated__lt=F('amount')
                    ).order_by('created_at')
                    
                    for pending_inv in pending_investments:
                        if amount_to_allocate <= 0:
                            break
                        
                        available = pending_inv.amount - pending_inv.amount_allocated
                        
                        if amount_to_allocate <= available:
                            PendingInvestment.objects.filter(id=pending_inv.id).update(
                                amount_allocated=F('amount_allocated') + amount_to_allocate
                            )
                            amount_to_allocate = Decimal('0.00')
                        else:
                            PendingInvestment.objects.filter(id=pending_inv.id).update(
                                amount_allocated=F('amount')
                            )
                            amount_to_allocate -= available
                    
                    InvestmentTransaction.objects.create(
                        investment=investment,
                        amount=amount,
                        transaction_date=transaction_date,
                        is_contribution=True,
                        is_redemption=False,
                    )
                    
                    investment.total_contributed += amount
                    investment.current_balance += amount
                    investment.save()
                    
                    log_action(
                        request.user,
                        f"Aporte de R$ {amount:.2f} adicionado ao investimento {investment.name}",
                        f"Investimento ID: {investment.id}, Corretora: {investment.broker.name}, Tipo: {investment.investment_type.name}, Data: {transaction_date}"
                    )
                    messages.success(request, f"Aporte de R$ {amount:.2f} adicionado com sucesso ao investimento {investment.name}.")
                    
            except Investment.DoesNotExist:
                messages.error(request, "Investimento não encontrado.")
            except Exception as e:
                messages.error(request, f"Erro ao adicionar aporte: {str(e)}")
            
            return redirect('investment:investments')
        
        elif action == 'redeem_investment':
            investment_id = request.POST.get('investment_id')
            amount = Decimal(request.POST.get('amount', '0'))
            account_id = request.POST.get('account_id')
            transaction_date = request.POST.get('transaction_date')
            
            if amount <= 0:
                messages.error(request, "O valor a ser resgatado deve ser maior que zero.")
                return redirect('investment:investments')
            
            if not account_id:
                messages.error(request, "É necessário selecionar uma conta para receber o resgate.")
                return redirect('investment:investments')
            
            try:
                with db_transaction.atomic():
                    investment = Investment.objects.get(id=investment_id)
                    
                    if amount > investment.current_balance:
                        messages.error(request, f"O valor a ser resgatado (R$ {amount:.2f}) excede o saldo atual do investimento (R$ {investment.current_balance:.2f}).")
                        return redirect('investment:investments')
                    
                    account = Account.objects.get(id=account_id)
                    
                    # Capturar saldo antes do resgate
                    old_balance = investment.current_balance
                    
                    # Criar InvestmentTransaction
                    InvestmentTransaction.objects.create(
                        investment=investment,
                        amount=-amount,
                        transaction_date=transaction_date,
                        is_contribution=False,
                        is_redemption=True,
                        account=account,
                    )
                    
                    # Atualizar Investment
                    investment.current_balance -= amount
                    if investment.current_balance == 0:
                        investment.status = 'resgatado'
                    investment.save()
                    
                    # Creditar na Account
                    Account.objects.filter(id=account_id).update(
                        balance=F('balance') + amount
                    )
                    
                    log_action(
                        request.user,
                        f"Resgate de investimento {investment.name}",
                        f"Investimento ID: {investment.id}, Valor resgatado: R$ {amount:.2f}, Saldo anterior: R$ {old_balance:.2f}, Saldo restante: R$ {investment.current_balance:.2f}, Conta destino: {account.name} (ID: {account.id}), Data: {transaction_date}"
                    )
                    messages.success(request, f"Resgate de R$ {amount:.2f} realizado com sucesso. Valor creditado na conta {account.name}.")
                    
            except Investment.DoesNotExist:
                messages.error(request, "Investimento não encontrado.")
            except Account.DoesNotExist:
                messages.error(request, "Conta não encontrada.")
            except Exception as e:
                messages.error(request, f"Erro ao realizar resgate: {str(e)}")
            
            return redirect('investment:investments')
        
        elif action == 'update_status':
            investment_id = request.POST.get('investment_id')
            status = request.POST.get('status')
            
            if status not in ['ativo', 'resgatado']:
                messages.error(request, "Status inválido. Deve ser 'ativo' ou 'resgatado'.")
                return redirect('investment:investments')
            
            try:
                investment = Investment.objects.get(id=investment_id)
                old_status = investment.status
                investment.status = status
                investment.save()
                
                log_action(
                    request.user,
                    f"Status do investimento {investment.name} alterado",
                    f"Investimento ID: {investment.id}, Status anterior: {old_status}, Novo status: {status}"
                )
                messages.success(request, f"Status do investimento {investment.name} alterado para '{investment.get_status_display()}'.")
                
            except Investment.DoesNotExist:
                messages.error(request, "Investimento não encontrado.")
            except Exception as e:
                messages.error(request, f"Erro ao alterar status: {str(e)}")
            
            return redirect('investment:investments')
        
        elif action == 'edit_investment':
            investment_id = request.POST.get('investment_id')
            broker_id = request.POST.get('broker_id')
            investment_type_id = request.POST.get('investment_type_id')
            name = request.POST.get('name', '').strip()
            
            if not name:
                messages.error(request, "O nome do investimento é obrigatório.")
                return redirect('investment:investments')
            
            try:
                investment = Investment.objects.get(id=investment_id)
                broker = Broker.objects.get(id=broker_id)
                investment_type = InvestmentType.objects.get(id=investment_type_id)
                
                # Verificar se nova combinação não conflita
                existing = Investment.objects.filter(broker=broker, name=name).exclude(id=investment_id).first()
                if existing:
                    messages.error(request, f"Já existe um investimento com a corretora '{broker.name}' e nome '{name}'.")
                    return redirect('investment:investments')
                
                old_name = investment.name
                investment.broker = broker
                investment.investment_type = investment_type
                investment.name = name
                investment.save()
                
                log_action(
                    request.user,
                    f"Investimento editado: {old_name} -> {investment.name}",
                    f"Investimento ID: {investment.id}, Corretora: {broker.name}, Tipo: {investment_type.name}, Nome anterior: {old_name}, Novo nome: {investment.name}"
                )
                messages.success(request, f"Investimento atualizado com sucesso.")
                
            except Investment.DoesNotExist:
                messages.error(request, "Investimento não encontrado.")
            except Broker.DoesNotExist:
                messages.error(request, "Corretora não encontrada.")
            except InvestmentType.DoesNotExist:
                messages.error(request, "Tipo de investimento não encontrado.")
            except Exception as e:
                messages.error(request, f"Erro ao editar investimento: {str(e)}")
            
            return redirect('investment:investments')
        
        return redirect('investment:investments')
