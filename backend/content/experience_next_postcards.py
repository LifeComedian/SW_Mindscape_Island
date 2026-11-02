"""Postcard designs and allocation limits."""
from copy import deepcopy
from content.holiday_reading_v6 import POSTCARDS
from content.experience_next_library import STOCK
INITIAL=deepcopy(POSTCARDS[:3])
for card in INITIAL:
    card['name']=card['author_label']+'的明信片'
FACES=[{'id':p['id'],'name':p['name'],'text':'','art_id':p['art_id']} for p in POSTCARDS]
FACES += [{'id':r[0],'name':r[1],'text':'','art_id':'next.card.'+r[0]} for r in STOCK['postcards']]
VISITORS={9:(3,'宋以宁'),10:(5,'程越'),11:(7,'唐沐')}
