"""Optional, requested background with separate provenance. Never automatic padding."""
from urllib.parse import urlparse
import ast
from decimal import Decimal
from live.distillation import require
from live.distillation_source import digest
from live.numeric_fidelity import inventory


class BackgroundResolver:
    def __init__(self,recovery,catalog=()):
        self.recovery=recovery;self.catalog={x['id']:x for x in catalog}

    def descriptors(self):
        return [{k:r.get(k) for k in ('id','title','url')} for r in self.catalog.values()]

    def resolve(self,request,source):
        require(isinstance(request.get('why_needed'),str) and request['why_needed'].strip(),'Background needs a concrete editorial purpose')
        if request.get('kind') == 'calculation':
            return calculation(request, source)
        record=self.catalog.get(request.get('evidence_id'))
        if record:
            record=dict(record)
            require(record.get('quote') and record.get('document_text') and record['quote'] in record['document_text'],'Background quote must be exact evidence')
            require(record.get('url') and record.get('fetched_at'),'Background provenance missing')
        else:
            url=request.get('url')
            require(isinstance(url,str) and urlparse(url).hostname in self.recovery.allowed_hosts,'Background URL must be independently configured')
            page=self.recovery.retrieve(url)
            require(page['content_complete'],'Background document incomplete')
            record={'url':page['url'],'fetched_at':page['fetched_at'],'document_text':page['text'],'quote':page['text'],'document_ref':page['document_ref']}
        require(record['url']!=source.get('url'),'Background must be independent of the original source')
        record.update(evidence_id=digest([record['url'],record['quote']])[:20],source_hash=digest(record['document_text']),
                      requested_for=request['why_needed'],role='external_background_not_original_author_claim')
        return record


def calculation(request, source):
    """Only an explicit editor request can create this private addition record."""
    operands = request.get('operands')
    require(isinstance(operands, dict) and 1 <= len(operands) <= 6, 'Calculation operands missing')
    values = {}
    for name, item in operands.items():
        require(name.isidentifier() and isinstance(item, dict), 'Invalid operand')
        require(item.get('source_quote') and item['source_quote'] in source['original_text'], 'Operand lacks exact source evidence')
        values[name] = Decimal(str(item['value']))
        require(values[name].is_finite(), 'Non-finite operand')
        require(any(Decimal(v) == values[name] for v, unit in inventory(item['source_quote'])), 'Operand value differs from cited source')
    expression = request.get('expression', '')
    require(isinstance(expression, str) and len(expression) <= 120, 'Invalid expression')
    def visit(node):
        if isinstance(node, ast.Name) and node.id in values: return values[node.id]
        if isinstance(node, ast.Constant) and type(node.value) in (int, float): return Decimal(str(node.value))
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)):
            a, b = visit(node.left), visit(node.right)
            if isinstance(node.op, ast.Add): return a + b
            if isinstance(node.op, ast.Sub): return a - b
            if isinstance(node.op, ast.Mult): return a * b
            return a / b
        raise ValueError('Only named Decimal arithmetic is supported')
    result = visit(ast.parse(expression, mode='eval').body)
    require(result.is_finite(), 'Non-finite calculation')
    record = {'role': 'editorial_calculation_not_original_author_claim', 'expression': expression,
              'operands': operands, 'result': str(result), 'requested_for': request['why_needed'],
              'url': source.get('url'), 'source_hash': source['source_hash'],
              'quote': f'{expression} = {result}', 'binding_validation': 'semantic QA required'}
    record['evidence_id'] = digest(record)[:20]
    return record
