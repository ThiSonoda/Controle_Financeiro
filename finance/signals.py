# finance/signals.py
from django.db.models.signals import pre_save, post_save, pre_delete
from django.db.models import F
from django.dispatch import receiver
from .models import Transaction, Account


def update_account_balance(account, amount, transaction_type, is_paid):
    """
    Atualiza o saldo da conta baseado no tipo de transação e se está paga.
    
    - Receitas (IN): adiciona ao saldo quando is_paid=True
    - Despesas (EX): subtrai do saldo quando is_paid=True
    - Quando is_paid=False, reverte a operação
    """
    if not is_paid:
        return  # Não atualiza saldo se não estiver paga
    
    if transaction_type == Transaction.TYPE_INCOME:
        # Receita: adiciona ao saldo
        Account.objects.filter(id=account.id).update(
            balance=F('balance') + amount
        )
    elif transaction_type == Transaction.TYPE_EXPENSE:
        # Despesa: subtrai do saldo
        Account.objects.filter(id=account.id).update(
            balance=F('balance') - amount
        )


def revert_account_balance(account, amount, transaction_type, is_paid):
    """
    Reverte o saldo da conta (usado quando uma transação é deletada ou is_paid muda de True para False).
    """
    if not is_paid:
        return  # Não havia impacto no saldo
    
    if transaction_type == Transaction.TYPE_INCOME:
        # Receita: subtrai do saldo (reverte)
        Account.objects.filter(id=account.id).update(
            balance=F('balance') - amount
        )
    elif transaction_type == Transaction.TYPE_EXPENSE:
        # Despesa: adiciona ao saldo (reverte)
        Account.objects.filter(id=account.id).update(
            balance=F('balance') + amount
        )


@receiver(pre_save, sender=Transaction)
def transaction_pre_save(sender, instance, **kwargs):
    """
    Antes de salvar, verifica se houve mudança no is_paid, conta, valor ou tipo.
    Se a transação já existe e estava paga, reverte o saldo antigo antes de aplicar o novo.
    """
    if instance.pk:  # Transação existente
        try:
            old_instance = Transaction.objects.get(pk=instance.pk)
            old_is_paid = old_instance.is_paid
            old_account = old_instance.account
            old_amount = old_instance.amount
            old_type = old_instance.type
            
            # Verifica se houve alguma mudança relevante
            has_changes = (
                old_is_paid != instance.is_paid or 
                old_account != instance.account or 
                old_amount != instance.amount or 
                old_type != instance.type
            )
            
            if has_changes:
                # Reverter o impacto da transação antiga se estava paga
                if old_is_paid:
                    revert_account_balance(old_account, old_amount, old_type, old_is_paid)
                
                # Armazenar informações para uso no post_save
                instance._old_account = old_account
                instance._old_is_paid = old_is_paid
                instance._old_amount = old_amount
                instance._old_type = old_type
        except Transaction.DoesNotExist:
            pass


@receiver(post_save, sender=Transaction)
def transaction_post_save(sender, instance, created, **kwargs):
    """
    Após salvar, atualiza o saldo da conta se is_paid=True.
    O pre_save já reverteu o impacto antigo se necessário, então aqui apenas aplicamos o novo.
    """
    if created:
        # Nova transação: atualiza saldo se estiver paga
        if instance.is_paid:
            update_account_balance(instance.account, instance.amount, instance.type, instance.is_paid)
    else:
        # Transação existente: aplica o novo impacto se estiver paga
        # O pre_save já reverteu o impacto antigo se necessário
        if instance.is_paid:
            update_account_balance(instance.account, instance.amount, instance.type, instance.is_paid)
    
    # Limpar atributos temporários
    if hasattr(instance, '_old_account'):
        delattr(instance, '_old_account')
    if hasattr(instance, '_old_is_paid'):
        delattr(instance, '_old_is_paid')
    if hasattr(instance, '_old_amount'):
        delattr(instance, '_old_amount')
    if hasattr(instance, '_old_type'):
        delattr(instance, '_old_type')


@receiver(pre_delete, sender=Transaction)
def transaction_pre_delete(sender, instance, **kwargs):
    """
    Antes de deletar, reverte o impacto no saldo se a transação estava paga.
    """
    if instance.is_paid:
        revert_account_balance(instance.account, instance.amount, instance.type, instance.is_paid)

