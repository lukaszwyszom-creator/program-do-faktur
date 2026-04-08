from sqlalchemy import create_engine, text
import os, uuid
from datetime import datetime, timezone

engine = create_engine(os.environ['DATABASE_URL'])
sid = str(uuid.uuid4())
token_json = '{"session_token":"FAKE_TOKEN_WORKER_TEST"}'
with engine.begin() as conn:
    conn.execute(text(
        'INSERT INTO ksef_sessions (id, nip, environment, auth_method, session_reference, '
        'token_metadata_json, status, expires_at, created_at, updated_at) '
        'VALUES (:id, :nip, :env, :method, :ref, CAST(:token AS jsonb), :status, NULL, :now, :now)'
    ), {
        'id': sid, 'nip': '1111111111', 'env': 'test', 'method': 'token',
        'ref': 'REF_FAKE_001', 'token': token_json,
        'status': 'active', 'now': datetime.now(timezone.utc),
    })
print('OK Session:', sid)
