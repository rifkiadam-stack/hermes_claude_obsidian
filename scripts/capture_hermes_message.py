"""Read-only capture of one explicitly selected persisted Hermes USER message.

Not a Telegram event issuer: platform_message_id may honestly be absent. The
caller must bind expected session/chat/user, full-message SHA256 and exact spans.
Returns a retained text snapshot for create-only guarded staging; no DB/vault
writes, automatic message discovery, mode inference, or credential access.
"""
from pathlib import Path
import hashlib,sqlite3,re
MAX_BYTES=1024*1024

def read_source(*,db_path,message_id,session_id,chat_id,user_id,expected_message_sha256,
                source_start,source_end,command_start,command_end,thread_id=None):
    if type(message_id) is not int or message_id<=0 or not all(type(x) is str and x for x in (session_id,chat_id,user_id)):
        raise ValueError('explicit persisted message/session/chat/user identity required')
    if not re.fullmatch('[0-9a-f]{64}',expected_message_sha256):
        raise ValueError('independently frozen complete-message hash required')
    p=Path(db_path).resolve(strict=True)
    c=sqlite3.connect(p.as_uri()+'?mode=ro',uri=True)
    c.row_factory=sqlite3.Row
    try:
        c.execute('PRAGMA query_only=ON');c.execute('BEGIN')
        meta=c.execute('SELECT m.session_id,m.role,m.active,s.source,s.chat_id,s.user_id,s.thread_id,length(CAST(m.content AS BLOB)) AS byte_length FROM messages m JOIN sessions s ON m.session_id=s.id WHERE m.id=?',(message_id,)).fetchone()
        if meta is None or (meta['session_id'],meta['role'],meta['active'],meta['source'],meta['chat_id'],meta['user_id'],meta['thread_id'])!=(session_id,'user',1,'telegram',chat_id,user_id,thread_id):
            raise ValueError('selected user message or conversation identity mismatch')
        if type(meta['byte_length']) is not int or not 0<meta['byte_length']<=MAX_BYTES:
            raise ValueError('unsupported message size')
        row=c.execute('SELECT content,platform_message_id FROM messages WHERE id=?',(message_id,)).fetchone()
        text=row['content'];full=text.encode('utf-8',errors='strict')
        if hashlib.sha256(full).hexdigest()!=expected_message_sha256:
            raise ValueError('original persisted message changed')
        spans=(source_start,source_end,command_start,command_end)
        if any(type(x) is not int for x in spans) or not (source_start==0<source_end<=command_start<command_end==len(text)):
            raise ValueError('whole supplied-source prefix and disjoint command suffix required')
        if text[source_end:command_start] not in ('\n\n','\r\n\r\n'):
            raise ValueError('source/command boundary must be original blank separator')
        command=text[command_start:command_end]
        if command not in ('ingest','ingest verbatim','ingest rapikan','ingest transkrip'):
            raise ValueError('explicit ingest command required; no source-selected mode')
        payload=text[:source_end].encode('utf-8',errors='strict')
        if any((ord(ch)<32 and ch not in '\t\n\r') or 127<=ord(ch)<=159 for ch in payload.decode('utf-8')):
            raise ValueError('unsupported source control characters')
        return dict(source_kind='hermes_persisted_user_message',locator=f'hermes-session://{session_id}/messages/{message_id}',
            message_id=message_id,session_id=session_id,chat_id=chat_id,user_id=user_id,thread_id=thread_id,
            platform_message_id=row['platform_message_id'],message_sha256=expected_message_sha256,
            selection_codepoints=[source_start,source_end],selection_utf8_bytes=[0,len(payload)],
            command_codepoints=[command_start,command_end],original_command=command,
            source_sha256=hashlib.sha256(payload).hexdigest(),source_length=len(payload),source_bytes=payload,
            guarantee='exact UTF-8 text persisted by Hermes; not native Telegram transport authentication')
    finally:
        c.close()
