"""Opt-in native MySQL parser/block/reorg regressions on a disposable schema.

Run only with SRC101_NATIVE_TEST=1 and RDS_DATABASE=stampdex_src101_regression_20261003.
No Bitcoin signing, broadcasting or production database is used.
"""
import hashlib
import json
import os
from datetime import datetime, timezone

import pymysql
import pytest

pytestmark = pytest.mark.skipif(os.getenv('SRC101_NATIVE_TEST') != '1', reason='isolated native fixture required')

import config
from index_core import database
from index_core.blocks import BlockProcessor, commit_and_update_block
from index_core.caching import clear_all_caches
from index_core.src101 import check_src101_inputs, parse_src101, update_src101_owners

OWNER = '1BoatSLRHtKNngkdXEeobR76b53LETtpyT'
BUYER = '1BitcoinEaterAddressDontSendf59kuE'
THIRD = '1CounterpartyXXXXXXXXXXXXXXXUWLpVr'
TOKEN = 'YWxpY2U='
DEPLOY = hashlib.sha256(b'stampdex-src101-native-fixture').hexdigest()
HEIGHT = 940101
TIME = 1_800_000_000
YEAR = 31_536_000


def connect():
    assert os.environ['RDS_DATABASE'] == 'stampdex_src101_regression_20261003'
    assert os.environ['RDS_HOSTNAME'] == '127.0.0.1' and os.environ['RDS_PORT'] == '55893'
    return pymysql.connect(host='127.0.0.1', port=55893, user=os.environ['RDS_USER'],
                           password=os.environ['RDS_PASSWORD'], database=os.environ['RDS_DATABASE'],
                           autocommit=False, charset='utf8mb4')


def one(db, sql, args=()):
    with db.cursor() as cursor:
        cursor.execute(sql, args)
        return cursor.fetchone()


def owner(db):
    with db.cursor(pymysql.cursors.DictCursor) as cursor:
        cursor.execute('SELECT * FROM owners WHERE deploy_hash=%s AND tokenid_utf8=%s', (DEPLOY, 'alice'))
        return cursor.fetchone()


def parse(db, payload, height, sequence=1, creator=OWNER, timestamp=None, prior=None):
    tx_hash = hashlib.sha256(f'{height}/{sequence}/{payload}'.encode()).hexdigest()
    raw = check_src101_inputs(json.dumps(payload), tx_hash, height)
    assert raw is not None
    raw.update(tx_hash=tx_hash, tx_index=height * 100 + sequence, block_index=height,
               creator=creator, destination=OWNER, destination_nvalue=0, prev_tx_hash=bytes.fromhex('11'*32),
               block_time=datetime.fromtimestamp(timestamp or (TIME + height - HEIGHT), timezone.utc))
    _, row = parse_src101(db, raw, prior or [], height)
    return row


def add_block(db, height):
    with db.cursor() as cursor:
        cursor.execute('INSERT INTO blocks(block_index,block_hash,block_time,previous_block_hash,indexed) '
                       'VALUES(%s,%s,%s,%s,NULL)',
                       (height, hashlib.sha256(f'block/{height}'.encode()).hexdigest(),
                        datetime.fromtimestamp(TIME + height - HEIGHT, timezone.utc),
                        hashlib.sha256(f'block/{height-1}'.encode()).hexdigest()))


def finalize(db, height, rows, commit=True):
    add_block(db, height)
    processor = BlockProcessor(db)
    processor.processed_src101_in_block = rows
    processor.finalize_block(height, TIME + height - HEIGHT, [row['tx_hash'] for row in rows], height + 100)
    if commit:
        commit_and_update_block(db, height, height + 100, block_hash=hashlib.sha256(f'block/{height}'.encode()).hexdigest())
        assert one(db, 'SELECT indexed FROM blocks WHERE block_index=%s', (height,)) == (1,)


def mint(db, *, primary=False):
    payload = {'p':'SRC-101','op':'MINT','hash':DEPLOY,'toaddress':OWNER,'tokenid':[TOKEN],
               'dua':'1','prim':'true' if primary else 'false','sig':'','coef':'1000'}
    row = parse(db, payload, HEIGHT)
    assert row.get('valid') == 1, row.get('status')
    finalize(db, HEIGHT, [row])
    return row


def transfer(db, height, *, creator=OWNER, destination=BUYER, sequence=1, prior=None, timestamp=None):
    return parse(db, {'p':'SRC-101','op':'TRANSFER','hash':DEPLOY,'toaddress':destination,'tokenid':TOKEN},
                 height, sequence=sequence, creator=creator, timestamp=timestamp, prior=prior)


@pytest.fixture(scope="module", autouse=True)
def forward_schema():
    connection = connect()
    with connection.cursor() as cursor:
        database.apply_schema_updates(connection, cursor)
    connection.close()


@pytest.fixture
def db():
    connection = connect()
    clear_all_caches()
    with connection.cursor() as cursor:
        for table in ('owners','SRC101Valid','SRC101','src101price','recipients','transactions','blocks'):
            cursor.execute(f'DELETE FROM `{table}`')
        cursor.execute('INSERT INTO blocks(block_index,block_hash,block_time,txlist_hash,messages_hash,indexed) '
                       'VALUES(%s,%s,%s,%s,%s,1)',
                       (HEIGHT-1, hashlib.sha256(f'block/{HEIGHT-1}'.encode()).hexdigest(),
                        datetime.fromtimestamp(TIME-1, timezone.utc), 'a'*64, 'b'*64))
    deploy = {'p':'SRC-101','op':'DEPLOY','tx_hash':DEPLOY,'tx_index':1,'block_index':HEIGHT-1,
              'valid':1,'lim':1000,'pri':{'0':0},'mintstart':0,'mintend':2**64-1,'idua':1,
              'rec':[OWNER],'owner':OWNER,'creator':OWNER,'imglp':'https://example.invalid/','imgf':'png',
              'block_time':datetime.fromtimestamp(TIME-1,timezone.utc)}
    database.insert_into_src101_tables(connection, [deploy])
    connection.commit()
    yield connection
    connection.rollback()
    connection.close()
    clear_all_caches()


def test_native_raw_transfer_sql_commit_and_reopen(db):
    assert HEIGHT >= config.BTC_SRC101_IMG_OPTIONAL_BLOCK
    mint(db)
    row = transfer(db, HEIGHT+1)
    assert row.get('valid') == 1, row.get('status')
    assert row['tokenid'] == TOKEN and row['tokenid_utf8'] == 'alice'
    finalize(db, HEIGHT+1, [row])
    with connect() as reopened:
        actual = owner(reopened)
        assert actual['owner'] == BUYER and actual['preowner'] == OWNER
        assert actual['tokenid'] == TOKEN and actual['tokenid_utf8'] == 'alice'
        assert actual['expire_timestamp'] == TIME + YEAR
        assert actual['prim'] == 0 and actual['address_btc'] is None
        assert one(reopened, 'SELECT tokenid,tokenid_utf8 FROM SRC101Valid WHERE tx_hash=%s', (row['tx_hash'],)) == (TOKEN,'alice')


def test_native_same_block_transfer_transfer_renew(db):
    mint(db)
    first = transfer(db, HEIGHT+1)
    second = transfer(db, HEIGHT+1, creator=BUYER, destination=THIRD, sequence=2, prior=[first])
    renewed = parse(db, {'p':'SRC-101','op':'RENEW','hash':DEPLOY,'tokenid':TOKEN,'dua':'1'},
                    HEIGHT+1, creator=THIRD, sequence=3, prior=[first,second])
    assert all(row.get('valid') == 1 for row in (first,second,renewed)), [row.get('status') for row in (first,second,renewed)]
    finalize(db, HEIGHT+1, [first,second,renewed])
    actual = owner(db)
    assert actual['owner'] == THIRD and actual['preowner'] == BUYER
    assert actual['expire_timestamp'] == TIME + 2*YEAR
    assert actual['tokenid'] == TOKEN


def test_native_wrong_owner_and_expired_transfer_rejected(db):
    mint(db)
    wrong = transfer(db, HEIGHT+1, creator=THIRD)
    expired = transfer(db, HEIGHT+1, sequence=2, timestamp=TIME+YEAR)
    assert wrong.get('valid') != 1 and 'INVALID OWNER' in wrong.get('status','')
    assert expired.get('valid') != 1 and 'EXPIRE TIME' in expired.get('status','')
    finalize(db, HEIGHT+1, [wrong,expired])
    assert owner(db)['owner'] == OWNER
    assert one(db, 'SELECT COUNT(*) FROM SRC101 WHERE block_index=%s', (HEIGHT+1,)) == (2,)
    assert one(db, 'SELECT COUNT(*) FROM SRC101Valid WHERE block_index=%s', (HEIGHT+1,)) == (0,)


def test_native_block_rollback_leaves_prior_owner(db):
    mint(db)
    row = transfer(db, HEIGHT+1)
    finalize(db, HEIGHT+1, [row], commit=False)
    assert owner(db)['owner'] == BUYER
    db.rollback()
    assert owner(db)['owner'] == OWNER
    assert one(db, 'SELECT COUNT(*) FROM SRC101 WHERE block_index=%s', (HEIGHT+1,)) == (0,)
    assert one(db, 'SELECT COUNT(*) FROM blocks WHERE block_index=%s', (HEIGHT+1,)) == (0,)


def test_native_reorg_purge_and_rebuild_restores_prior_owner(db):
    mint(db)
    first = transfer(db, HEIGHT+1)
    finalize(db, HEIGHT+1, [first])
    retained = owner(db)
    second = transfer(db, HEIGHT+2, creator=BUYER, destination=THIRD)
    finalize(db, HEIGHT+2, [second])
    database.purge_block_db(db, HEIGHT+2)
    database.rebuild_owners(db, HEIGHT+1)
    rebuilt = owner(db)
    for field in ('p','deploy_hash','tokenid','tokenid_utf8','owner','preowner','expire_timestamp','last_update','prim'):
        assert rebuilt[field] == retained[field], field
    assert one(db, 'SELECT COUNT(*) FROM SRC101Valid WHERE block_index=%s', (HEIGHT+2,)) == (0,)


def test_native_lookup_migration_is_forward_only_and_idempotent(db):
    expected = {'SRC20':'idx_src20_block_tx','SRC101':'idx_src101_block_tx','SRC101Valid':'idx_src101valid_block_tx'}
    with db.cursor() as cursor:
        for table,index in expected.items():
            cursor.execute(f'ALTER TABLE `{table}` DROP INDEX `{index}`')
        database.apply_schema_updates(db,cursor)
        database.apply_schema_updates(db,cursor)
        for table,index in expected.items():
            cursor.execute('SELECT COLUMN_NAME FROM information_schema.statistics WHERE TABLE_SCHEMA=DATABASE() '
                           'AND TABLE_NAME=%s AND INDEX_NAME=%s ORDER BY SEQ_IN_INDEX',(table,index))
            assert cursor.fetchall() == (('block_index',),('tx_hash',))


def test_native_setrecord_history_survives_reorg(db):
    mint(db)
    address = parse(db, {'p':'SRC-101','op':'SETRECORD','hash':DEPLOY,'tokenid':TOKEN,
                         'type':'address','data':{'btc':OWNER},'prim':'true'}, HEIGHT+1)
    text = parse(db, {'p':'SRC-101','op':'SETRECORD','hash':DEPLOY,'tokenid':TOKEN,
                      'type':'txt','data':{'profile':'native fixture'},'prim':'true'},
                 HEIGHT+1,sequence=2,prior=[address])
    assert all(row.get('valid') == 1 for row in (address,text)), [row.get('status') for row in (address,text)]
    finalize(db,HEIGHT+1,[address,text])
    retained = owner(db)
    history = one(db,'SELECT address_btc,address_eth,txt_data FROM SRC101Valid WHERE tx_hash=%s',(text['tx_hash'],))
    assert history[0] == OWNER
    assert history[1] is None
    assert json.loads(history[2]) == {'profile':'native fixture'}
    later = transfer(db,HEIGHT+2)
    finalize(db,HEIGHT+2,[later])
    database.purge_block_db(db,HEIGHT+2)
    database.rebuild_owners(db,HEIGHT+1)
    rebuilt = owner(db)
    for field in ('owner','address_btc','address_eth','txt_data','prim','expire_timestamp','last_update'):
        assert rebuilt[field] == retained[field], field


def test_native_reorg_retained_transfer_resets_primary(db):
    mint(db,primary=True)
    first = transfer(db,HEIGHT+1)
    finalize(db,HEIGHT+1,[first])
    assert owner(db)['prim'] == 0
    later = transfer(db,HEIGHT+2,creator=BUYER,destination=THIRD)
    finalize(db,HEIGHT+2,[later])
    database.purge_block_db(db,HEIGHT+2)
    database.rebuild_owners(db,HEIGHT+1)
    assert owner(db)['prim'] == 0


@pytest.mark.parametrize('selection', ['MINT', 'SETRECORD'])
def test_native_two_name_primary_replay_matches_live(db, selection):
    mint(db, primary=True)
    bob = 'Ym9i'
    row = parse(db, {'p':'SRC-101','op':'MINT','hash':DEPLOY,'toaddress':OWNER,
                     'tokenid':[bob],'dua':'1','prim':'true' if selection == 'MINT' else 'false',
                     'sig':'','coef':'1000'}, HEIGHT+1)
    assert row.get('valid') == 1, row.get('status')
    finalize(db, HEIGHT+1, [row])
    retained_height = HEIGHT+1
    if selection == 'SETRECORD':
        selected = parse(db, {'p':'SRC-101','op':'SETRECORD','hash':DEPLOY,'tokenid':bob,
                             'type':'address','data':{'btc':OWNER},'prim':'true'}, HEIGHT+2)
        assert selected.get('valid') == 1, selected.get('status')
        finalize(db, HEIGHT+2, [selected])
        retained_height = HEIGHT+2
    with db.cursor() as cursor:
        cursor.execute('SELECT tokenid,prim,address_btc FROM owners ORDER BY tokenid')
        retained = cursor.fetchall()
    assert sum(row[1] for row in retained) == 1
    later = transfer(db, retained_height+1)
    finalize(db, retained_height+1, [later])
    database.purge_block_db(db, retained_height+1)
    database.rebuild_owners(db, retained_height)
    with db.cursor() as cursor:
        cursor.execute('SELECT tokenid,prim,address_btc FROM owners ORDER BY tokenid')
        assert cursor.fetchall() == retained


@pytest.mark.parametrize('field,corrupted', [
    ('prim', 0), ('address_btc', BUYER), ('address_eth', 'corrupted-fixture'),
    ('txt_data', '{"profile":"corrupted fixture"}'),
])
def test_native_record_only_projection_drift_is_rebuilt(db, field, corrupted):
    mint(db, primary=True)
    record = parse(db, {'p':'SRC-101','op':'SETRECORD','hash':DEPLOY,'tokenid':TOKEN,
                       'type':'txt','data':{'profile':'retained fixture'},'prim':'true'}, HEIGHT+1)
    assert record.get('valid') == 1, record.get('status')
    finalize(db, HEIGHT+1, [record])
    retained = owner(db)
    with db.cursor() as cursor:
        cursor.execute(f'UPDATE owners SET `{field}`=%s WHERE deploy_hash=%s AND tokenid=%s',
                       (corrupted, DEPLOY, TOKEN))
    db.commit()
    with db.cursor() as cursor:
        existing = database.get_existing_owners(cursor)
        history = database.get_src101_valid_list(cursor, HEIGHT+1)
    calculated = database.calculate_owners(db, history)
    assert database.owners_need_update(existing, calculated)
    database.rebuild_owners(db, HEIGHT+1)
    rebuilt = owner(db)
    for key in ('owner','preowner','prim','address_btc','address_eth','txt_data','expire_timestamp','last_update'):
        assert rebuilt[key] == retained[key], key


def test_native_missing_historical_records_blocks_destructive_rebuild(db):
    mint(db, primary=True)
    record = parse(db, {'p':'SRC-101','op':'SETRECORD','hash':DEPLOY,'tokenid':TOKEN,
                       'type':'txt','data':{'profile':'retain without guessing'},'prim':'true'}, HEIGHT+1)
    assert record.get('valid') == 1, record.get('status')
    finalize(db, HEIGHT+1, [record])
    retained = owner(db)
    with db.cursor() as cursor:
        cursor.execute('UPDATE SRC101Valid SET address_btc=NULL,address_eth=NULL,txt_data=NULL WHERE tx_hash=%s',
                       (record['tx_hash'],))
    db.commit()
    with pytest.raises(ValueError, match='history is incomplete; reparse the actual chain'):
        database.rebuild_owners(db, HEIGHT+1)
    assert owner(db) == retained


def test_native_primary_replay_forgets_transferred_address(db):
    mint(db, primary=True)
    moved = transfer(db, HEIGHT+1)
    finalize(db, HEIGHT+1, [moved])
    selected = parse(db, {'p':'SRC-101','op':'SETRECORD','hash':DEPLOY,'tokenid':TOKEN,
                         'type':'address','data':{'btc':BUYER},'prim':'true'}, HEIGHT+2, creator=BUYER)
    assert selected.get('valid') == 1, selected.get('status')
    finalize(db, HEIGHT+2, [selected])
    bob = parse(db, {'p':'SRC-101','op':'MINT','hash':DEPLOY,'toaddress':OWNER,
                     'tokenid':['Ym9i'],'dua':'1','prim':'true','sig':'','coef':'1000'}, HEIGHT+3)
    assert bob.get('valid') == 1, bob.get('status')
    finalize(db, HEIGHT+3, [bob])
    with db.cursor() as cursor:
        existing = database.get_existing_owners(cursor)
        history = database.get_src101_valid_list(cursor, HEIGHT+3)
    calculated = database.calculate_owners(db, history)
    assert sum(row[9] for row in existing) == 2
    assert sum(row['prim'] for row in calculated.values()) == 2
    assert not database.owners_need_update(existing, calculated)


def owner_snapshot(db):
    with db.cursor() as cursor:
        cursor.execute('SELECT tokenid,owner,preowner,expire_timestamp,address_btc,address_eth,txt_data,prim,img,last_update,id,`index` FROM owners ORDER BY tokenid')
        return cursor.fetchall()


def assert_replay_matches(db, height):
    retained = owner_snapshot(db)
    with db.cursor() as cursor:
        cursor.execute('UPDATE owners SET last_update=0')
    db.commit()
    database.rebuild_owners(db, height)
    assert owner_snapshot(db) == retained


@pytest.mark.parametrize('last_op', ['SETRECORD', 'TRANSFER', 'RENEW'])
def test_native_same_block_primary_event_order(db, last_op):
    a = parse(db, {'p':'SRC-101','op':'MINT','hash':DEPLOY,'toaddress':OWNER,
                   'tokenid':[TOKEN],'dua':'1','prim':'true','sig':'','coef':'1000'}, HEIGHT)
    b = parse(db, {'p':'SRC-101','op':'MINT','hash':DEPLOY,'toaddress':OWNER,
                   'tokenid':['Ym9i'],'dua':'1','prim':'true','sig':'','coef':'1000'}, HEIGHT, sequence=2, prior=[a])
    if last_op == 'SETRECORD':
        payload = {'p':'SRC-101','op':'SETRECORD','hash':DEPLOY,'tokenid':TOKEN,
                   'type':'address','data':{'btc':OWNER},'prim':'true'}
    elif last_op == 'TRANSFER':
        payload = {'p':'SRC-101','op':'TRANSFER','hash':DEPLOY,'tokenid':'Ym9i','toaddress':BUYER}
    else:
        payload = {'p':'SRC-101','op':'RENEW','hash':DEPLOY,'tokenid':TOKEN,'dua':'1'}
    last = parse(db,payload,HEIGHT,sequence=3,prior=[a,b])
    assert all(row.get('valid') == 1 for row in (a,b,last)), [row.get('status') for row in (a,b,last)]
    finalize(db,HEIGHT,[a,b,last])
    primaries = one(db,'SELECT GROUP_CONCAT(tokenid_utf8 ORDER BY tokenid_utf8) FROM owners WHERE prim=1')[0]
    assert primaries == {'SETRECORD':'alice','TRANSFER':None,'RENEW':'bob'}[last_op]
    assert_replay_matches(db,HEIGHT)


def test_native_running_transfer_resets_records_before_renew(db):
    mint(db,primary=True)
    moved=transfer(db,HEIGHT+1)
    renewed=parse(db,{'p':'SRC-101','op':'RENEW','hash':DEPLOY,'tokenid':TOKEN,'dua':'1'},
                  HEIGHT+1,sequence=2,creator=BUYER,prior=[moved])
    assert renewed['valid'] == 1
    assert renewed['address_btc'] is None and renewed['txt_data'] is None and not renewed['prim']
    finalize(db,HEIGHT+1,[moved,renewed])
    assert_replay_matches(db,HEIGHT+1)


@pytest.mark.parametrize('offset',[0,99])
def test_native_expired_renew_is_rejected_without_owner_change(db,offset):
    mint(db)
    retained=owner_snapshot(db)
    renewed=parse(db,{'p':'SRC-101','op':'RENEW','hash':DEPLOY,'tokenid':TOKEN,'dua':'1'},
                  HEIGHT+1,timestamp=TIME+YEAR+offset)
    assert renewed.get('valid') != 1 and 'EXPIRE TIME' in renewed.get('status','')
    finalize(db,HEIGHT+1,[renewed])
    assert owner_snapshot(db) == retained
    assert_replay_matches(db,HEIGHT+1)


def test_native_expired_remint_preserves_preowner_and_replaces_image(db):
    mint(db)
    with db.cursor() as cursor:
        cursor.execute('UPDATE SRC101Valid SET imglp=%s WHERE tx_hash=%s',('https://example.invalid/new;',DEPLOY))
    db.commit(); clear_all_caches()
    reminted=parse(db,{'p':'SRC-101','op':'MINT','hash':DEPLOY,'toaddress':BUYER,
                      'tokenid':[TOKEN],'dua':'1','prim':'true','sig':'','coef':'1000'},
                   HEIGHT+1,timestamp=TIME+YEAR+1)
    assert reminted.get('valid') == 1, reminted.get('status')
    finalize(db,HEIGHT+1,[reminted])
    assert owner(db)['preowner'] == OWNER and owner(db)['owner'] == BUYER
    assert owner(db)['img'] == reminted['img'][0]
    assert_replay_matches(db,HEIGHT+1)


@pytest.mark.parametrize('image', [None, 'https://example.invalid/'+'a'*3900+';z.png'],ids=['explicit-null','long-semicolon-url'])
def test_native_exact_mint_image_history_and_rebuild(db,image):
    with db.cursor() as cursor:
        cursor.execute('UPDATE SRC101Valid SET imglp=NULL,imgf=NULL WHERE tx_hash=%s',(DEPLOY,))
    db.commit(); clear_all_caches()
    payload={'p':'SRC-101','op':'MINT','hash':DEPLOY,'toaddress':OWNER,
             'tokenid':[TOKEN],'dua':'1','prim':'false','sig':'','coef':'1000'}
    if image is not None: payload['img']=[image]
    row=parse(db,payload,HEIGHT)
    assert row.get('valid') == 1, row.get('status')
    assert row['img'] == [image]
    finalize(db,HEIGHT,[row])
    assert json.loads(one(db,'SELECT mint_img FROM SRC101Valid WHERE tx_hash=%s',(row['tx_hash'],))[0]) == [image]
    assert owner(db)['img'] == image
    assert_replay_matches(db,HEIGHT)
    retained=owner_snapshot(db)
    with db.cursor() as cursor:
        cursor.execute('UPDATE SRC101Valid SET mint_img=NULL WHERE tx_hash=%s',(row['tx_hash'],))
    db.commit()
    with pytest.raises(ValueError,match='MINT image history is incomplete'):
        database.rebuild_owners(db,HEIGHT)
    assert owner_snapshot(db) == retained


def test_native_rebuild_insert_failure_rolls_back_owner_deletion(db,monkeypatch):
    mint(db)
    with db.cursor() as cursor: cursor.execute('UPDATE owners SET last_update=0')
    db.commit();retained=owner_snapshot(db)
    def fail(*args): raise RuntimeError('injected rebuild insertion failure')
    monkeypatch.setattr(database,'insert_owners',fail)
    with pytest.raises(RuntimeError,match='injected rebuild'):
        database.rebuild_owners(db,HEIGHT)
    assert owner_snapshot(db) == retained


def test_native_parser_build_metadata_same_version_history(db,monkeypatch):
    from index_core.source_attestation import collect_indexer_source_metadata
    from index_core import node_health
    with db.cursor() as cursor: cursor.execute("DELETE FROM node_version_history WHERE component_name='stamps_indexer'")
    db.commit()
    monkeypatch.setenv('STAMPS_APPROVED_BUILD_ID','stampdex-src101-native-candidate')
    first=collect_indexer_source_metadata()
    database.upsert_node_version(db,'stamps_indexer','1.9.3',extra_info=first)
    database.upsert_node_version(db,'stamps_indexer','1.9.3',extra_info=first)
    assert one(db,"SELECT COUNT(*) FROM node_version_history WHERE component_name='stamps_indexer'") == (1,)
    second=dict(first,build_id='stampdex-src101-native-candidate-2')
    database.upsert_node_version(db,'stamps_indexer','1.9.3',extra_info=second)
    assert one(db,"SELECT COUNT(*) FROM node_version_history WHERE component_name='stamps_indexer'") == (2,)
    assert one(db,"SELECT COUNT(*) FROM node_version_history WHERE component_name='stamps_indexer' AND superseded_at IS NULL") == (1,)
    reopened=connect()
    from index_core.database_manager import db_manager
    monkeypatch.setattr(db_manager,'connect',lambda:reopened)
    node_health.persist_indexer_version()
    latest=one(db,"SELECT extra_info FROM node_version_history WHERE component_name='stamps_indexer' AND superseded_at IS NULL")[0]
    db.rollback()
    latest=one(db,"SELECT extra_info FROM node_version_history WHERE component_name='stamps_indexer' AND superseded_at IS NULL")[0]
    assert json.loads(latest) == first


def test_native_eth_signed_record_public_vector_and_rebuild(db):
    from eth_account import Account
    from eth_account.messages import encode_defunct
    from pathlib import Path
    mint(db)
    account=Account.create()
    # Public message matches the previous txid of vin0 in this fixture.
    message='11'*32
    signature=bytes(account.sign_message(encode_defunct(text=message)).signature).hex()
    payload={'p':'SRC-101','op':'SETRECORD','hash':DEPLOY,'tokenid':TOKEN,
             'type':'address','data':{'btc':OWNER,'eth':signature},'prim':'true'}
    row=parse(db,payload,HEIGHT+1)
    assert row.get('valid') == 1, row.get('status')
    finalize(db,HEIGHT+1,[row])
    assert owner(db)['address_eth'] == account.address[2:]
    assert_replay_matches(db,HEIGHT+1)
    receipt={'classification':'native parser/MySQL fixture; no chain transaction',
             'messageText':message,'signatureHex':signature,'recoveredAddress':account.address,
             'persistedAddressEth':account.address[2:],'wirePayload':payload,
             'mainnetTransactions':0}
    Path(r'C:\universe\stampdex\audits\implementation-20261003\protocol\SRC101_ETH_PUBLIC_VECTOR.json').write_text(json.dumps(receipt,indent=2))
