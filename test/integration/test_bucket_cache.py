######################################################################
#
# File: test/integration/test_bucket_cache.py
#
# Copyright 2026 Backblaze Inc. All Rights Reserved.
#
# License https://www.backblaze.com/using_b2_code.html
#
######################################################################
"""
The persistent bucket name -> id cache (``SqliteAccountInfo`` behind ``AuthInfoCache``, the
setup the CLI uses) must cope with a bucket being deleted and recreated under the same name,
whether this client does it or another one does (Backblaze/B2_Command_Line_Tool#567).
"""

from __future__ import annotations

import time

import pytest

from b2sdk.v3 import AuthInfoCache, B2Api, SqliteAccountInfo
from b2sdk.v3.exception import BucketIdNotFound, DuplicateBucketName, NonExistentBucket


@pytest.fixture
def sqlite_cached_api(tmp_path, b2_auth_data, realm):
    account_info = SqliteAccountInfo(file_name=str(tmp_path / 'account_info'))
    api = B2Api(account_info, AuthInfoCache(account_info))
    api.authorize_account(*b2_auth_data, realm=realm)
    yield api, account_info
    account_info.close()


def _recreate(api, bucket_name, attempts=12, delay=5.0):
    """B2 can take a moment to release a deleted bucket's name."""
    for attempt in range(attempts):
        try:
            return api.create_bucket(bucket_name, 'allPrivate')
        except DuplicateBucketName:
            if attempt == attempts - 1:
                raise
            time.sleep(delay)


def _delete_quietly(api, bucket_name):
    try:
        api.delete_bucket(api.get_bucket_by_name(bucket_name))
    except Exception:  # cleanup only; the bucket manager removes leftovers by prefix
        pass


def test_bucket_recreated_with_same_name_by_this_client(sqlite_cached_api, bucket_manager):
    api, account_info = sqlite_cached_api
    bucket_name = bucket_manager.new_bucket_name()
    try:
        old_bucket = api.create_bucket(bucket_name, 'allPrivate')
        assert api.get_bucket_by_name(bucket_name).id_ == old_bucket.id_  # now cached
        api.delete_bucket(old_bucket)
        new_bucket = _recreate(api, bucket_name)
        assert new_bucket.id_ != old_bucket.id_

        resolved = api.get_bucket_by_name(bucket_name)
        assert resolved.id_ == new_bucket.id_
        assert list(resolved.ls()) == []  # the server accepts the id we resolved
        assert account_info.list_bucket_names_ids().count((bucket_name, new_bucket.id_)) == 1
        assert account_info.get_bucket_name_or_none_from_bucket_id(old_bucket.id_) is None
    finally:
        _delete_quietly(api, bucket_name)


def test_bucket_recreated_with_same_name_elsewhere(sqlite_cached_api, b2_api, bucket_manager):
    # `b2_api` plays another machine: the same account with its own (in-memory) cache
    api, account_info = sqlite_cached_api
    bucket_name = bucket_manager.new_bucket_name()
    try:
        old_bucket = api.create_bucket(bucket_name, 'allPrivate')
        assert api.get_bucket_by_name(bucket_name).id_ == old_bucket.id_  # now cached here

        b2_api.delete_bucket(b2_api.get_bucket_by_name(bucket_name))
        new_bucket = _recreate(b2_api, bucket_name)

        stale_bucket = api.get_bucket_by_name(bucket_name)
        assert stale_bucket.id_ == old_bucket.id_  # nothing has told this client yet
        with pytest.raises(BucketIdNotFound):  # the first use fails: bad_bucket_id
            list(stale_bucket.ls())
        # ...and that answer evicted the stale entry, so the next lookup is right
        assert account_info.get_bucket_id_or_none_from_bucket_name(bucket_name) is None
        assert api.get_bucket_by_name(bucket_name).id_ == new_bucket.id_
    finally:
        _delete_quietly(api, bucket_name)


def test_bucket_deleted_elsewhere_is_reported_missing_after_one_failure(
    sqlite_cached_api, b2_api, bucket_manager
):
    api, account_info = sqlite_cached_api
    bucket_name = bucket_manager.new_bucket_name()
    api.create_bucket(bucket_name, 'allPrivate')
    stale_bucket = api.get_bucket_by_name(bucket_name)
    b2_api.delete_bucket(b2_api.get_bucket_by_name(bucket_name))

    # b2_list_buckets answers a dead id with an empty list, not an error; this path evicts too
    with pytest.raises(BucketIdNotFound):
        stale_bucket.get_fresh_state()
    assert account_info.get_bucket_id_or_none_from_bucket_name(bucket_name) is None
    with pytest.raises(NonExistentBucket):
        api.get_bucket_by_name(bucket_name)
