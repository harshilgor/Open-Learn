"""Bounded arithmetic verification with no eval, functions, variables, or code."""
import ast
import math
import operator

OPERATORS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
             ast.Div: operator.truediv, ast.Pow: operator.pow}


def arithmetic(expression: str) -> float:
    if len(expression) > 160:
        raise ValueError("expression_limit")
    tree = ast.parse(expression, mode="eval")
    if len(list(ast.walk(tree))) > 40:
        raise ValueError("expression_limit")
    def calculate(node):
        if isinstance(node, ast.Constant) and type(node.value) in {int, float}:
            value = float(node.value)
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            value = calculate(node.operand) * (-1 if isinstance(node.op, ast.USub) else 1)
        elif isinstance(node, ast.BinOp) and type(node.op) in OPERATORS:
            left, right = calculate(node.left), calculate(node.right)
            if isinstance(node.op, ast.Pow) and abs(right) > 8:
                raise ValueError("exponent_limit")
            value = OPERATORS[type(node.op)](left, right)
        else:
            raise ValueError("unsupported_expression")
        if not isinstance(value, (int, float)) or not math.isfinite(value) or abs(value) > 1e12:
            raise ValueError("numeric_limit")
        return value
    return calculate(tree.body)


def verify(check) -> bool:
    try:
        return math.isfinite(check.expected) and abs(arithmetic(check.expression) - check.expected) <= check.tolerance
    except (ValueError, SyntaxError, TypeError, ArithmeticError):
        return False
