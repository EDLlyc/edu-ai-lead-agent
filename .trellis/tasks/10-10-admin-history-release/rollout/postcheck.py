"""Read-only deployed contract/log checks; no password, auth session, provider or publish mutation."""
import datetime,json,subprocess
from pathlib import Path
STAGE=Path(__file__).resolve().parent
CANDIDATE=json.loads((STAGE/'candidate.json').read_text())
API='edu-ai-lead-agent-acquisition-api-1'
# Dependency overrides exist only in this one-off Python process, never in the running API.
# This verifies role-protected route projections against live data, not an end-user login.
CODE='''import asyncio,json
from datetime import UTC,datetime,timedelta
from uuid import uuid4
import httpx
from sqlalchemy import text
from app.api_main import app
from app.api.admin_dependencies import require_admin
from app.api.dependencies import get_session
from app.application.services.admin_auth import AdminPrincipal
from app.core.config import get_settings
from app.infrastructure.db.session import create_engine,create_session_factory
async def main():
 settings=get_settings();engine=create_engine(settings);factory=create_session_factory(engine)
 app.state.settings=settings
 async def readonly():
  async with factory() as session:
   await session.execute(text('SET TRANSACTION READ ONLY'))
   try:yield session
   finally:await session.rollback()
 async def principal():return AdminPrincipal(user_id=uuid4(),username='deployment-check',display_name='deployment-check',role='owner',session_id=uuid4(),expires_at=datetime.now(UTC)+timedelta(minutes=5))
 app.dependency_overrides[get_session]=readonly
 app.dependency_overrides[require_admin]=principal
 output={'method':'isolated-process role projection; read-only DB transactions; real HTTP auth rejection checked separately'}
 try:
  async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://localhost') as client:
   for path in ['/api/v1/admin/auth/me','/api/v1/admin/models','/api/v1/admin/wechat/account-options','/api/v1/admin/wechat/publish-jobs?limit=20','/api/v1/admin/audit-events?limit=1']:
    response=await client.get(path);assert response.status_code==200,(path,response.status_code)
    assert response.headers.get('cache-control')=='no-store'
    data=response.json()
    if '/models' in path:
     assert all('load_errors' in c for c in data['consumers'])
     fresh={c['service']:c for c in data['consumers'] if c['reporting']}
     for service in ['acquisition-api','content-worker','wecom-infographic-producer']:
      c=fresh[service];assert c['load_errors']=={},service+' load diagnostics not fresh/healthy'
      age=(datetime.now(UTC)-datetime.fromisoformat(c['seen_at'].replace('Z','+00:00'))).total_seconds();assert 0<=age<150,service+' heartbeat stale'
     output['consumers']=[{'service':c['service'],'reporting':c['reporting'],'load_errors':c['load_errors'],'seen_at':c['seen_at']} for c in data['consumers']]
    elif 'account-options' in path:
     output['account_count']=len(data['items'])
     for account in data['items']:
      stats=await client.get('/api/v1/admin/wechat/accounts/'+account['id']+'/stats?days=30');assert stats.status_code==200
      body=stats.json();assert {'range_start','range_end','missing_dates'}<=body.keys()
      output.setdefault('statistics',[]).append({'range_start':body['range_start'],'range_end':body['range_end'],'missing_days':len(body['missing_dates']),'known_days':len(body['daily'])})
    elif 'publish-jobs' in path:
     assert {'items','total','offset','limit','business_timezone'}<=data.keys()
     assert data['offset']==0 and data['limit']==20
     output['job_page']={k:data[k] for k in ['total','offset','limit','business_timezone']}
   for query in ['status=invalid','offset=-1','limit=1000','date_from=2026-10-11&date_to=2026-10-10']:
    response=await client.get('/api/v1/admin/wechat/publish-jobs?'+query);assert response.status_code==422,(query,response.status_code)
   output['invalid_queries_rejected']=4
   async def editor():return AdminPrincipal(user_id=uuid4(),username='deployment-check',display_name='deployment-check',role='editor',session_id=uuid4(),expires_at=datetime.now(UTC)+timedelta(minutes=5))
   app.dependency_overrides[require_admin]=editor
   assert (await client.get('/api/v1/admin/models')).status_code==403
   assert (await client.get('/api/v1/admin/audit-events')).status_code==403
   assert (await client.get('/api/v1/admin/wechat/publish-jobs?limit=20')).status_code==200
   output['role_projection_checks']='owner reads/editor refusal PASS'
 finally:await engine.dispose()
 print(json.dumps(output,ensure_ascii=False))
asyncio.run(main())
'''
result=subprocess.run(['docker','exec','-i',API,'python','-'],input=CODE,text=True,capture_output=True,timeout=90)
if result.returncode:
 error=STAGE/'postcheck-error.log';error.write_text(result.stdout+'\n'+result.stderr);error.chmod(0o600)
 raise SystemExit('Read-only contract check failed; inspect root-only postcheck-error.log')
report={'at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'image':CANDIDATE['image'],'contracts':json.loads(result.stdout.strip().splitlines()[-1])}
services=['acquisition-api','acquisition-worker','content-scheduler','content-worker','wecom-infographic-producer','wecom-dispatcher']
report['services']={}
for service in services:
 name='edu-ai-lead-agent-'+service+'-1'
 item=json.loads(subprocess.run(['docker','inspect',name],text=True,capture_output=True,check=True).stdout)[0]
 logs=subprocess.run(['docker','logs','--since',item['State']['StartedAt'],name],text=True,capture_output=True,check=True)
 content=logs.stdout+'\n'+logs.stderr
 record={'running':item['State']['Running'],'restarts':item['RestartCount'],'image':item['Image'],'tracebacks':content.count('Traceback (most recent call last)'),'model_overlay_errors':content.count('console_model_keys_unavailable'),'heartbeat_errors':content.count('console_model_key_heartbeat_failed')}
 assert record['running'] and record['restarts']==0 and record['image']==CANDIDATE['image'] and record['tracebacks']==0 and record['model_overlay_errors']==0 and record['heartbeat_errors']==0,service+' health/log check failed'
 report['services'][service]=record
(STAGE/'postcheck-result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(report,ensure_ascii=False,indent=2))
