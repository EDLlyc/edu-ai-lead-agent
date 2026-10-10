"""Read-only live base checks. Emit only allowlisted deployment metadata."""
import datetime,hashlib,json,subprocess
from pathlib import Path
ROOT=Path('/opt/edu-ai-lead-agent')
API='edu-ai-lead-agent-acquisition-api-1'
def run(args,stdin=None):
 r=subprocess.run(args,input=stdin,text=True,capture_output=True,check=False,timeout=60)
 if r.returncode:raise RuntimeError('Read-only check failed: '+args[0])
 return r.stdout
names=run(['docker','ps','-a','--filter','label=com.docker.compose.project=edu-ai-lead-agent','--format','{{.Names}}']).splitlines()
containers=json.loads(run(['docker','inspect',*names]))
result={'at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'containers':{x['Name'].lstrip('/'):{'id':x['Id'],'image':x['Image'],'running':x['State']['Running'],'status':x['State']['Status'],'restarts':x['RestartCount'],'health':x['State'].get('Health',{}).get('Status')} for x in containers},'config_hashes':{name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in ['.env','.release.env','compose.yaml']}}
manifest={'alembic/versions/20261010_0060_wechat_publish_occupancy.py': 'absent', 'alembic/versions/20261010_0061_model_key_load_errors.py': 'absent', 'app/api/v1/routes/admin_models.py': '5afd174d34db8e1740da4f4be58c51b8b5bffd41d98909cf93e2b5dfa05dba12', 'app/api/v1/routes/admin_wechat.py': '2a66dfa5a096270a70c85ef7d2ace523d23a98834c4e46f7ce5e222e92f35e44', 'app/api_main.py': 'ba6d32850511d890738cccc74d787bba18ba980882aa41634dee12b3b6dc21c9', 'app/application/services/wechat_admin.py': '6a2880a6cf81fca49b4efeb5d27ad1fc8bc3fb0b500fdc5ad14f7b16d72dcbc2', 'app/application/services/wechat_stats.py': 'f80b9266413752306d4593011d090050869d49b087bdb9cf247c261f6b1abe04', 'app/infrastructure/db/models.py': '04f219408a5d6a69f054dacf1b22c5be72fa445bf9a216f9e8e13785c2a1dc8f', 'app/infrastructure/model_api_keys_overlay.py': 'e4a77bfc9d6f23d7aab390685882c37791551fcb69c758760093f2a9fe058193', 'app/infrastructure/wechat_official_account/admin_client.py': 'fa3ae5696288d639a377dade771e24102ebf3a1c25b0b7711caea94385c841cb', 'app/schemas/admin_models.py': '8fbfcd64913c837559a4ec08eb23521b1e83972864022a487df8863a916703eb', 'app/schemas/admin_wechat.py': 'e4c05d5382c0d58c9ce8cadd4011f1685b08e5de17c7f034f7dc971362bc07fe'}
code='''import hashlib,json
from pathlib import Path
manifest=MANIFEST
actual={name:hashlib.sha256((Path('/app')/name).read_bytes()).hexdigest() if (Path('/app')/name).is_file() else 'absent' for name in manifest}
print(json.dumps({'file_count':len(manifest),'base_matches':actual==manifest,'mismatches':[name for name in manifest if manifest[name]!=actual[name]]}))
'''.replace('MANIFEST',repr(manifest))
result['base']=json.loads(run(['docker','exec','-i',API,'python','-'],code))
queries={'schema':'SELECT version_num FROM alembic_version','acquisition_running':"SELECT count(*) FROM acquisition_jobs WHERE status='running'",'slots_active':"SELECT count(*) FROM content_slot_jobs WHERE status IN ('queued','running')",'copy_running':"SELECT count(*) FROM copy_generation_jobs WHERE status='running'",'infographic_active':"SELECT count(*) FROM news_infographic_jobs WHERE status IN ('queued','running')",'delivery_running':"SELECT count(*) FROM wecom_delivery_jobs WHERE status='running'",'sources_enabled':'SELECT count(*) FROM sources WHERE enabled','seeds_enabled':"SELECT count(*) FROM sources WHERE enabled AND managed_by='seed'",'stored_model_keys':'SELECT count(*) FROM model_api_keys','wechat_accounts':'SELECT count(*) FROM wechat_accounts','publish_jobs':'SELECT count(*) FROM wechat_publish_jobs','open_publish_jobs':"SELECT count(*) FROM wechat_publish_jobs WHERE status IN ('scheduled','submitting','publishing','outcome_unknown')",'occupied_conflicts':"SELECT count(*) FROM (SELECT 1 FROM wechat_publish_jobs WHERE status IN ('scheduled','submitting','publishing','outcome_unknown','succeeded') GROUP BY account_id,media_id HAVING count(*)>1) AS conflicts"}
code='''import asyncio,os,json
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
async def main():
 engine=create_async_engine(os.environ['DATABASE_URL'])
 try:
  async with engine.connect() as conn:
   await conn.execute(text('SET TRANSACTION READ ONLY'))
   result={}
   for name,query in QUERIES.items():result[name]=(await conn.execute(text(query))).scalar_one()
   await conn.rollback();print(json.dumps(result))
 finally:await engine.dispose()
asyncio.run(main())
'''.replace('QUERIES',repr(queries))
result['counts']=json.loads(run(['docker','exec','-i',API,'python','-'],code))
print(json.dumps(result,indent=2))
