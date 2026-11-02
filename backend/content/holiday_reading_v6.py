"""Reading excerpts and fictional island postcards."""
BOOKS=[
    {'id':'walden','name':'《瓦尔登湖》· 独处','author':'亨利·戴维·梭罗','section':'Solitude',
     'source_url':'https://www.gutenberg.org/files/205/205-h/205-h.htm',
     'original':'I never found the companion that was so companionable as solitude.',
     'translation':'我从未找到过一个伙伴，能像独处这样与我相契。',
     'note':'节选谈的是独处的体验。你可以想想：一个人待着时，什么让你感到自在？也可以只读这句话，不作回答。'},
    {'id':'meditations','name':'《沉思录》· 回到内心','author':'马可·奥勒留','section':'第四卷第三节；Meric Casaubon 英译',
     'source_url':'https://www.gutenberg.org/files/2680/2680-h/2680-h.htm',
     'original':'Afford then thyself this retiring continually, and thereby refresh and renew thyself.',
     'translation':'那么，就常常给自己这样退回内心的机会，借此恢复精神，重新开始。',
     'note':'这一节先谈人们向往乡间、海边和山中，再把目光转向内在的安静。这里的导读只是阅读提示，不是书中原文。'},
    {'id':'stray_birds','name':'《飞鸟集》· 花的美','author':'拉宾德拉纳特·泰戈尔','section':'第154则',
     'source_url':'https://www.gutenberg.org/cache/epub/6524/pg6524-images.html',
     'original':'By plucking her petals you do not gather the beauty of the flower.',
     'translation':'摘下她的花瓣，并不能把花的美收集起来。',
     'note':'一则关于观看与占有的短诗。可以在读完后去看看窗边的花，留意这句话带给你的联想。'},
]
from content.holiday_reading_texts import PAGES, SECTIONS
for book in BOOKS:
    book.pop('note',None)
    book.pop('original',None)
    book.pop('translation',None)
    book['section']=SECTIONS[book['id']]
    if book['id']=='stray_birds':book['name']='《飞鸟集》· 飞鸟与世界'
    book['pages']=PAGES[book['id']]
    book['attribution']=book['author']+' · '+book['section']+'。据公版英文文本自译；此处为节选分页。'
    book['text']='\n\n'.join(book['pages'])+'\n\n'+book['attribution']
    book['art_id']='book.'+book['id']

POSTCARDS=[
    ('early_ferry','写给早起的自己','阿禾','今天终于赶上第一班船。天还淡淡的，船边一圈水像碎银子。到了岛上才发现相机留在住处，反而一路没急着拍照。早餐的面包有一点烤焦，我很喜欢那股香味。希望下次来时，还能记住今天这样慢慢走路的速度。'),
    ('window_rain','窗边等雨停','小乔','原本想把地图上每个地方都走一遍，结果午后下了雨。我在窗边喝完一杯茶，又续了一杯。隔壁桌的人帮我捡起掉下的铅笔，我们就聊起各自住的城市。雨停时，我已经不觉得这个下午被耽误了。把这段小小的意外寄给你。'),
    ('wood_boat','带不走的木船','远山','在木作桌边拼了一只小船，帆装得有点歪，拆下来又试了一次。最后没有带走，就把它留在架子上了。也许下一位游客会拿起来看看，也许只会从旁边经过。我想，一件小东西留在这里，也算替我多住了几天。'),
    ('evening_walk','晚饭后的灯','林间','傍晚海风凉下来，街上的窗户一扇扇亮了。我走得很慢，看见有人给门口的花浇水，有人抱着刚洗好的衣服上楼。晚饭没有什么特别，只是一碗热面，但我想记下这些普通的小事。愿你今天回家的路上，也有一盏让人放心的灯。'),
    ('next_visit','留给下次的事','柚子','离开前还有好多事没做：没看完那本书，没把速写画完，也没找到最好看的贝壳。不过这次终于不急着把清单划满了。我把书签夹在原处，给速写留了一块空白。下次如果还来，就从这些没做完的小事开始吧。'),
]
POSTCARDS=[{'id':key,'name':title,'text':text+'\n\n——'+author+'（虚构岛上游客，本项目原创）',
            'art_id':'postcard.'+key,'author_label':author,'source_type':'authored_fiction'}
           for key,title,author,text in POSTCARDS]
SOURCES={
    'postcard_theme_reference':'https://www.postcrossing.com/help/what-should-i-write-on-a-postcard',
    'postcard_notice':'借鉴日常见闻、风景、心情等题材；五张文字均为本项目原创，不冒充真实用户邮寄内容。',
    'uno_rules':'https://service.mattel.com/instruction_sheets/UNO%20Basic%20IS.pdf',
}
