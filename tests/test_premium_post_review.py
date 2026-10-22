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
