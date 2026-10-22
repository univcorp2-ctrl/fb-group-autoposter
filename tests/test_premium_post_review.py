import hashlib
import json

from src.estateboard_adapter import to_property
from src.premium_post_review import review_post_copy


def setup_case(tmp_path):
    row = {'propertyId': '1', 'property.label': '検証用マンション', 'property.price': 100000000,
           'property.allowBrokerSharing': True, 'publicationStatus': 'PUBLISHED'}
    source = tmp_path / 'source.json'
    source.write_text(json.dumps({'items': [row]}), encoding='utf-8')
    job = {'property_id': 'eb-1', 'payload_json': json.dumps(to_property(row))}
    target = {'group_id': '123', 'body': '検証用マンションのご紹介です。価格は10,000万円です。'}
    return row, source, job, target


def approved(body):
    return json.dumps({'approved': True, 'bodyHash': hashlib.sha256(body.encode()).hexdigest(), 'reason': '合成検証'})


def test_review_is_bound_to_latest_facts_and_exact_body(tmp_path):
    _, source, job, target = setup_case(tmp_path)
    calls = []
    def checker(prompt):
        calls.append(prompt)
        return approved(target['body'])
    options = {'source_path': source, 'review_dir': tmp_path / 'reviews', 'run_review': checker}
    assert review_post_copy(job, target, {'id': '123'}, **options)['approved']
    assert review_post_copy(job, target, {'id': '123'}, **options)['approved']
    assert len(calls) == 1
    target['body'] += ' 追加文'
    assert review_post_copy(job, target, {'id': '123'}, **options)['approved']
    assert len(calls) == 2


def test_changed_price_and_removed_permission_block_before_model(tmp_path):
    row, source, job, target = setup_case(tmp_path)
    def forbidden(_):
        raise AssertionError('No model review for ineligible or stale property facts')
    for changes in ({'property.price': 200000000}, {'property.allowBrokerSharing': False}):
        source.write_text(json.dumps({'items': [{**row, **changes}]}), encoding='utf-8')
        result = review_post_copy(job, target, {'id': '123'}, source_path=source,
                                  review_dir=tmp_path / 'reviews', run_review=forbidden)
        assert result['approved'] is False


def test_model_cannot_approve_different_body_hash(tmp_path):
    _, source, job, target = setup_case(tmp_path)
    result = review_post_copy(job, target, {}, source_path=source, review_dir=tmp_path / 'reviews',
                              run_review=lambda _: approved('different body'))
    assert result['approved'] is False


def test_reviewer_receives_verified_highlights_and_exact_signature_policy(tmp_path):
    row, source, job, target = setup_case(tmp_path)
    row['property.ownershipType'] = 'FREEHOLD'
    source.write_text(json.dumps({'items': [row]}), encoding='utf-8')
    job['payload_json'] = json.dumps(to_property(row))
    signature = '承認済み署名 https://example.com/contact'
    def checker(prompt):
        evidence = json.loads(prompt.split('<untrusted_data>')[1].split('</untrusted_data>')[0])
        assert '所有権' in evidence['facts']['highlights']
        assert evidence['group']['signature'] == signature
        assert evidence['group']['allow_links'] is False
        return approved(target['body'])
    assert review_post_copy(job, target, {'id': '123', 'allow_links': False, 'signature': signature},
        source_path=source, review_dir=tmp_path/'reviews', run_review=checker)['approved']



def test_failed_review_is_never_reinvoked_for_identical_task(tmp_path):
    _, source, job, target = setup_case(tmp_path)
    calls = []
    def failing_reviewer(prompt):
        calls.append(prompt)
        raise RuntimeError('synthetic unavailable')
    options = {'source_path': source, 'review_dir': tmp_path / 'reviews',
               'run_review': failing_reviewer}
    first = review_post_copy(job, target, {'id': '123'}, **options)
    second = review_post_copy(job, target, {'id': '123'}, **options)
    assert first == {'approved': False, 'reason': 'premium_review_unavailable:RuntimeError'}
    assert second == {'approved': False, 'reason': 'premium_review_once_consumed'}
    assert len(calls) == 1


def test_rejected_review_is_cached_without_repeated_model_call(tmp_path):
    _, source, job, target = setup_case(tmp_path)
    calls = []
    def rejected(prompt):
        calls.append(prompt)
        return json.dumps({'approved': False, 'bodyHash': hashlib.sha256(target['body'].encode()).hexdigest(),
                           'reason': 'unsupported factual claim'})
    options = {'source_path': source, 'review_dir': tmp_path / 'reviews',
               'run_review': rejected}
    first = review_post_copy(job, target, {'id': '123'}, **options)
    second = review_post_copy(job, target, {'id': '123'}, **options)
    assert first == second
    assert first['approved'] is False
    assert len(calls) == 1
