"""Seeded bounded sequential allocation, not a claim of joint-uniform composition."""
from dataclasses import replace
from decimal import Decimal,localcontext
import random
from .models import ELEMENTS,Parameters,finite,integer,MAX_CELLS

def enabled(rule):
    if not isinstance(rule,dict):raise ValueError('随机参数规则须为对象')
    value=rule.get('enabled',False)
    if type(value) is not bool:raise ValueError('随机开关必须为布尔值')
    return value

def bounds(rule,label,positive=False):
    if not isinstance(rule,dict):raise ValueError(label+'范围须为对象')
    lo=finite(rule.get('min'),label+'下界',positive);hi=finite(rule.get('max'),label+'上界',positive)
    if lo>hi:raise ValueError(label+'下界不能大于上界')
    return lo,hi

def generate_plan(base,count,seed,rule,cancelled=lambda:False):
    if not isinstance(rule,dict) or rule.get('kind') not in ('fixed','random'):raise ValueError('生成规则须为fixed/random')
    count=integer(count,'样本数',1);seed=integer(seed,'种子');rng=random.Random(seed)
    if count>5000:raise ValueError('最多5000样本')
    randomized=rule['kind']=='random'
    te_rule=rule.get('te',{}) if randomized else {};ne_rule=rule.get('ne',{}) if randomized else {}
    te_range=bounds(te_rule,'Te',True) if enabled(te_rule) else (base.Te,base.Te)
    ne_range=bounds(ne_rule,'实际Ne',True) if enabled(ne_rule) else (base.Ne,base.Ne)
    specs=rule.get('concentrations')
    if not isinstance(specs,list) or not 1<=len(specs)<=32:raise ValueError('须配置1–32个元素浓度')
    parsed=[];seen=set()
    for spec in specs:
        if not isinstance(spec,dict):raise ValueError('每个浓度规则须为对象')
        el=spec.get('el')
        if el not in ELEMENTS or el in seen:raise ValueError('元素无效或重复：'+str(el))
        seen.add(el);is_random=randomized and enabled(spec)
        lo,hi=bounds(spec,el+'浓度') if is_random else (finite(spec.get('fixed'),el+'固定浓度'),)*2
        if lo<0 or hi>100:raise ValueError(el+'浓度须在0–100%内')
        parsed.append({'el':el,'enabled':is_random,'min':lo,'max':hi})
    canonical={'kind':rule['kind'],'te':{'enabled':enabled(te_rule),'min':te_range[0],'max':te_range[1]},
               'ne':{'enabled':enabled(ne_rule),'min':ne_range[0],'max':ne_range[1]},'concentrations':parsed}
    with localcontext() as context:
        context.prec=50
        lower=[Decimal(str(s['min'])) for s in parsed];upper=[Decimal(str(s['max'])) for s in parsed]
        if any(s['enabled'] for s in parsed) and (sum(lower)>100 or sum(upper)<100):raise ValueError('浓度边界不可行：下界合计须≤100%，上界合计须≥100%（含固定值）')
        entries=[];cells=0
        for index in range(count):
            if cancelled():raise InterruptedError('确定随机计划生成已取消')
            values=list(lower);indices=[i for i,s in enumerate(parsed) if s['enabled']];rng.shuffle(indices)
            remaining=Decimal(100)-sum(lower[i] for i,s in enumerate(parsed) if not s['enabled'])
            for position,i in enumerate(indices):
                future=indices[position+1:];lo=max(lower[i],remaining-sum(upper[j] for j in future));hi=min(upper[i],remaining-sum(lower[j] for j in future))
                if lo>hi:raise ValueError('剩余浓度边界不可行')
                value=remaining if not future else lo+(hi-lo)*Decimal(str(rng.random()))
                values[i]=value;remaining-=value
            percentages=tuple(float(v) for v in values)
            actual=replace(base,elements=tuple(s['el'] for s in parsed),percentages=percentages,
                           Te=rng.uniform(*te_range) if enabled(te_rule) else base.Te,
                           Ne=rng.uniform(*ne_range) if enabled(ne_rule) else base.Ne).validated()
            cells+=actual.points
            if cells>MAX_CELLS:raise ValueError('计划超过5000000谱单元')
            entries.append({'name':f'sample-{index+1:05d}','parameters':actual.to_dict()})
    return {'kind':rule['kind'],'entries':entries,'sample_count':count,'rows':count,'elements':[s['el'] for s in parsed],
            'order':'预先保存的确定样本顺序','seed':seed,'rule':canonical,
            'distribution':'linear-uniform scalar parameters; shuffled feasible sequential concentration allocation, not joint uniform'}
