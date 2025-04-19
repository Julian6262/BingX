from decimal import Decimal


def get_decimal_places(step_size):
    d = Decimal(str(step_size))
    if d == d.to_integral_value():  # Проверяем, является ли число целым
        return 0
    else:
        return abs(d.as_tuple().exponent)
