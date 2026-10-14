"""Check simple numeric equalities without executing generated expressions."""
import ast
from fractions import Fraction
import re


def checked_numeric_equality(step):
    candidate=step.strip().strip('$').strip()
    candidate=candidate.replace('\\times','*').replace('\\div','/').replace('^','**')
    candidate=re.sub(r'\\frac\{(-?\d+(?:\.\d+)?)\}\{(-?\d+(?:\.\d+)?)\}',r'(\1/\2)',candidate)
    if len(candidate)>200 or candidate.count('=')!=1 or not re.fullmatch(r'[\d\s.()+*/=\-]+',candidate):return None
    def evaluate(source):
        tree=ast.parse(source.strip(),mode='eval')
        if len(list(ast.walk(tree)))>50:raise ValueError('Equation complexity exceeds bounds')
        def visit(node):
            if isinstance(node,ast.Expression):return visit(node.body)
            if isinstance(node,ast.Constant) and type(node.value) in (int,float):
                value=Fraction(str(node.value))
            elif isinstance(node,ast.UnaryOp) and isinstance(node.op,(ast.USub,ast.UAdd)):
                value=visit(node.operand)*(-1 if isinstance(node.op,ast.USub) else 1)
            elif isinstance(node,ast.BinOp) and isinstance(node.op,(ast.Add,ast.Sub,ast.Mult,ast.Div,ast.Pow)):
                left,right=visit(node.left),visit(node.right)
                if isinstance(node.op,ast.Add):value=left+right
                elif isinstance(node.op,ast.Sub):value=left-right
                elif isinstance(node.op,ast.Mult):value=left*right
                elif isinstance(node.op,ast.Div):value=left/right
                else:
                    if right.denominator!=1 or abs(right)>8:raise ValueError('Equation exponent exceeds bounds')
                    value=left**int(right)
            else:raise ValueError('Unsupported numeric equation')
            if abs(value)>10**12:raise ValueError('Equation magnitude exceeds bounds')
            return value
        return visit(tree)
    left,right=candidate.split('=')
    try:return evaluate(left)==evaluate(right)
    except (SyntaxError,ZeroDivisionError,OverflowError,ValueError):raise ValueError('Numeric equation could not be validated') from None
