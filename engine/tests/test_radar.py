import pytest
from datetime import datetime

from scientific_reading.library_service import LibraryService
from scientific_reading.models import PaperMetadata
from scientific_reading.paper_chat import PaperChatService
from scientific_reading.radar import RadarService
from scientific_reading.scope import use_scope, ScopeError


def metadata(doi='10.5555/radar-one', **extra):
    return {'title':'Single cell study of antiphospholipid syndrome','doi':doi,'pmid':'100001',
            'authors':['Ada Example'],'year':2025,'publication_date':'2025-04-03','journal':'Synthetic fixtures',
            'abstract_en':'A cohort study found no association in single cell measurements.',
            'publication_types':['cohort'],'status_flags':[],'oa_status':'unknown','fulltext_status':'not_requested',
            'source_url':'https://doi.org/'+doi if doi else 'https://europepmc.org/article/MED/100001','source_record_id':doi,**extra}


def page(items, more=False, cursor=None):
    return {'items':items,'total':len(items)+int(more),'returned':len(items),'skipped_invalid':0,'has_more':more,'next_cursor':cursor}


def setup(root, fetcher=None, interval=0):
    library=LibraryService(root)
    service=RadarService(library,fetcher or (lambda request:page([metadata()])))
    draft=service.draft({'name':'机制与反证','config':{'question':'单细胞证据如何解释抗磷脂综合征机制？','focus_groups':[['single cell','single-cell'],['antiphospholipid']],
        'research_types':['cohort'],'inclusion':['human'],'exclusion':['case report'],'interval_hours':interval}})
    return library,service,draft


def confirmed(service,draft):
    return service.confirm({'direction_id':draft['direction_id'],'expected_revision':draft['revision'],'confirmed':True})


def test_confirmation_gate_and_outbound_queries(tmp_path):
    calls=[]
    library,service,draft=setup(tmp_path,lambda request:calls.append(request))
    assert draft['status']=='draft' and len(draft['outbound_queries'])==6
    assert {'europe_pmc','crossref'}=={row['source'] for row in draft['outbound_queries']}
    with pytest.raises(ValueError,match='not_confirmed'):
        service.scan({'direction_id':draft['direction_id']})
    with pytest.raises(ValueError,match='confirmation'):
        service.confirm({'direction_id':draft['direction_id'],'expected_revision':1})
    assert calls==[] and library.conn.execute('SELECT COUNT(*) FROM items').fetchone()[0]==0
    confirmed(service,draft)
    assert service.tick()=={'status':'idle'}
    changed=service.draft({'direction_id':draft['direction_id'],'expected_revision':1,'name':'修订方向','config':draft['config']|{'question':'修订后的问题'}})
    assert changed['status']=='draft' and changed['revision']==2
    with pytest.raises(ValueError,match='conflict'):
        service.confirm({'direction_id':draft['direction_id'],'expected_revision':1,'confirmed':True})
    library.close()


def test_multisource_deduplication_history_feedback_and_admission(tmp_path):
    def fetch(request):
        return page([metadata(doi='https://doi.org/10.5555/RADAR-ONE') if request['source']=='crossref' else metadata()])
    library,service,draft=setup(tmp_path,fetch)
    direction=confirmed(service,draft); key=direction['direction_id']
    scan=service.scan({'direction_id':key})
    rows=service.candidates({'direction_id':key})
    assert len(scan['new_candidate_ids'])==1 and rows['total']==1
    candidate=rows['candidates'][0]
    assert candidate['assessment_current'] and len(candidate['discoveries'])==6
    assert library.conn.execute('SELECT COUNT(*) FROM items').fetchone()[0]==0
    assert service.notifications({})['new_relevant_candidates']==[]
    service.feedback({'direction_id':key,'candidate_id':candidate['candidate_id'],'state':'irrelevant','reason':'研究对象不符'})
    assert service.scan({'direction_id':key})['new_candidate_ids']==[]
    assert service.candidates({'direction_id':key})['candidates'][0]['state']=='irrelevant'
    payload={'direction_id':key,'candidate_id':candidate['candidate_id'],'metadata_sha':candidate['metadata_sha']}
    with pytest.raises(ValueError,match='confirmation'):
        service.admit(payload)
    admitted=service.admit(payload|{'confirmed':True})
    chat=PaperChatService(library).ensure(admitted['paper_id'])
    assert service.admit(payload|{'confirmed':True})['paper_id']==admitted['paper_id']
    assert PaperChatService(library).ensure(admitted['paper_id'])['session_id']==chat['session_id']
    assert library.conn.execute('SELECT COUNT(*) FROM items').fetchone()[0]==1
    assert library.conn.execute('SELECT COUNT(*) FROM attachments').fetchone()[0]==0
    library.close()
    library=LibraryService(tmp_path)
    assert RadarService(library).candidates({'direction_id':key})['candidates'][0]['feedback'][0]['reason']=='研究对象不符'
    library.close()


def test_assessment_quotes_versions_and_quiet_notifications(tmp_path):
    library,service,draft=setup(tmp_path)
    key=confirmed(service,draft)['direction_id'];service.scan({'direction_id':key})
    candidate=service.candidates({'direction_id':key})['candidates'][0]
    assessment={'verdict':'relevant',**{name:{'reason':'合成证据可用于核对研究设计与方向，不能推出因果。','evidence':[{'field':'abstract_en','quote':'cohort study'}]}
        for name in ('relevance','design','reading_value','timeliness')},'limitations':['仅摘要初筛']}
    payload={'direction_id':key,'candidate_id':candidate['candidate_id'],'metadata_sha':candidate['metadata_sha'],'config_revision':1,'expected_revision':0,'assessment':assessment}
    invalid=assessment|{'design':{'reason':'未验证','evidence':[{'field':'abstract_en','quote':'never appeared'}]}}
    with pytest.raises(ValueError,match='quote_not_found'):
        service.assess(payload|{'assessment':invalid})
    with pytest.raises(ValueError,match='source_changed'):
        service.assess(payload|{'metadata_sha':'0'*64})
    service.assess(payload)
    assert len(service.notifications({})['new_relevant_candidates'])==1
    service.notifications({'acknowledge':True})
    assert service.notifications({})['new_relevant_candidates']==[]
    service.feedback({'direction_id':key,'candidate_id':candidate['candidate_id'],'state':'irrelevant'})
    service.assess(payload|{'expected_revision':1})
    assert service.notifications({})['new_relevant_candidates']==[]
    library.close()


def test_incremental_partial_page_failure_resume_and_schedule(tmp_path):
    calls=[]; rounds={'value':0}
    def fetch(request):
        calls.append(request)
        if request['source']=='crossref' and rounds['value']==0:
            raise TimeoutError('synthetic timeout')
        return page([metadata()],more=rounds['value']==0,cursor='next-page' if rounds['value']==0 else None)
    library,service,draft=setup(tmp_path,fetch,interval=24)
    key=confirmed(service,draft)['direction_id']
    original=service.direction(key)['incremental']
    result=service.scan({'direction_id':key,'mode':'incremental'})
    assert result['status']=='partial' and len(result['errors'])==1
    after=service.direction(key)['incremental']
    scheduled=service.direction(key)
    assert (datetime.fromisoformat(scheduled['next_scan_at'])-datetime.fromisoformat(scheduled['updated_at'])).total_seconds()==60
    assert after['crossref']==original['crossref']
    assert after['europe_pmc']['watermark']==original['europe_pmc']['watermark'] and after['europe_pmc']['cursor']=='next-page'
    rounds['value']=1
    result=service.scan({'direction_id':key,'mode':'incremental'})
    assert result['status']=='complete' and result['new_candidate_ids']==[]
    epmc=[row for row in calls if row['source']=='europe_pmc']
    assert epmc[1]['params']['cursorMark']=='next-page' and epmc[1]['window_until']==epmc[0]['window_until']
    assert 'cursor' not in service.direction(key)['incremental']['europe_pmc']
    service.pause({'direction_id':key,'paused':True})
    with library.conn:library.conn.execute("UPDATE radar_directions SET next_scan_at='2000-01-01' WHERE direction_id=?",(key,))
    assert service.tick()=={'status':'idle'}
    service.pause({'direction_id':key,'paused':False})
    assert service.tick()['status']=='complete'
    library.close()


def test_partial_identifiers_and_existing_title_identity_are_not_duplicated(tmp_path):
    def fetch(request):
        return page([metadata(pmid=None) if request['source']=='crossref' else metadata(doi=None,source_record_id='MED:100001')])
    library,service,draft=setup(tmp_path,fetch)
    item=metadata()
    known=library.ingest(PaperMetadata(title=item['title'],year=item['year'],authors=item['authors']))['paper_id']
    key=confirmed(service,draft)['direction_id'];scan=service.scan({'direction_id':key})
    rows=service.candidates({'direction_id':key})['candidates']
    assert scan['errors']==[] and len(rows)==1 and rows[0]['library_paper_id']==known
    assert {row['source'] for row in rows[0]['discoveries']}=={'crossref','europe_pmc'}
    result=service.admit({'direction_id':key,'candidate_id':rows[0]['candidate_id'],'metadata_sha':rows[0]['metadata_sha'],'confirmed':True})
    assert result['paper_id']==known and library.conn.execute('SELECT COUNT(*) FROM items').fetchone()[0]==1
    library.close()


def test_identity_conflict_library_dedupe_and_paper_scope(tmp_path):
    def fetch(request):
        return page([metadata(),metadata('10.5555/other',pmid='100001')])
    library,service,draft=setup(tmp_path,fetch)
    known=library.ingest(PaperMetadata(title='Existing identity',doi='10.5555/radar-one',pmid='100001'))['paper_id']
    key=confirmed(service,draft)['direction_id'];service.scan({'direction_id':key})
    rows=service.candidates({'direction_id':key})['candidates']
    conflict=next(row for row in rows if row['metadata'].get('identity_conflict'))
    assert any(row['library_paper_id']==known for row in rows)
    with pytest.raises(ValueError,match='identity_conflict'):
        service.admit({'direction_id':key,'candidate_id':conflict['candidate_id'],'metadata_sha':conflict['metadata_sha'],'confirmed':True})
    chat=PaperChatService(library).ensure(known)
    scope={'instanceId':'fixture','scopeSessionId':chat['session_id'],'scopeFolderId':'__paper__','scopePaperId':known}
    with use_scope(scope),pytest.raises(ScopeError):
        service.list()
    library.close()
