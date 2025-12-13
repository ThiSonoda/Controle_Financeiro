from django import template
register = template.Library()

@register.filter
def get_item(mapping, key):
    return mapping.get(key)

@register.filter
def decimal_input(value):
    """
    Converte um valor decimal para string usando ponto como separador decimal.
    Útil para inputs HTML do tipo number que sempre esperam ponto.
    """
    if value is None:
        return '0.00'
    try:
        return f"{float(value):.2f}"
    except (ValueError, TypeError):
        return '0.00'
