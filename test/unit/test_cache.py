######################################################################
#
# File: test/unit/test_cache.py
#
# Copyright 2023 Backblaze Inc. All Rights Reserved.
#
# License https://www.backblaze.com/using_b2_code.html
#
######################################################################
from __future__ import annotations

from dataclasses import dataclass

import pytest
from apiver_deps import (
    AuthInfoCache,
    DummyCache,
    InMemoryAccountInfo,
    InMemoryCache,
    SqliteAccountInfo,
)
from pytest_lazy_fixtures import lf


@pytest.fixture
def dummy_cache():
    return DummyCache()


@pytest.fixture
def in_memory_cache():
    return InMemoryCache()


@pytest.fixture
def auth_info_cache():
    return AuthInfoCache(InMemoryAccountInfo())


@pytest.fixture
def sqlite_auth_info_cache(tmp_path):
    # the persistent store the CLI uses; the only backend that ever kept two rows
    # for one bucket name (Backblaze/B2_Command_Line_Tool#567)
    account_info = SqliteAccountInfo(file_name=str(tmp_path / 'account_info'))
    yield AuthInfoCache(account_info)
    account_info.close()


@pytest.fixture(
    scope='function',
    params=[lf('in_memory_cache'), lf('auth_info_cache'), lf('sqlite_auth_info_cache')],
)
def cache(request):
    return request.param


@dataclass
class DummyBucket:
    name: str
    id_: str


@pytest.fixture
def buckets():
    class InfBuckets(list):
        def __getitem__(self, item: int):
            self.extend(DummyBucket(f'bucket{i}', f'ID-{i}') for i in range(len(self), item + 1))
            return super().__getitem__(item)

    return InfBuckets()


class TestCache:
    def test_save_bucket(self, cache, buckets):
        cache.save_bucket(buckets[0])

    def test_get_bucket_id_or_none_from_bucket_name(self, cache, buckets):
        assert cache.get_bucket_id_or_none_from_bucket_name('bucket0') is None
        cache.save_bucket(buckets[0])
        assert cache.get_bucket_id_or_none_from_bucket_name('bucket0') == 'ID-0'

    def test_get_bucket_name_or_none_from_bucket_id(self, cache, buckets):
        assert cache.get_bucket_name_or_none_from_bucket_id('ID-0') is None
        cache.save_bucket(buckets[0])
        assert cache.get_bucket_name_or_none_from_bucket_id('ID-0') == 'bucket0'

    @pytest.mark.apiver(from_ver=3)
    def test_list_bucket_names_ids(self, cache, buckets):
        assert cache.list_bucket_names_ids() == []
        for i in range(2):
            cache.save_bucket(buckets[i])
        assert cache.list_bucket_names_ids() == [('bucket0', 'ID-0'), ('bucket1', 'ID-1')]

    def test_set_bucket_name_cache(self, cache, buckets):
        cache.set_bucket_name_cache([buckets[i] for i in range(2, 4)])

        assert cache.get_bucket_id_or_none_from_bucket_name('bucket1') is None
        assert cache.get_bucket_id_or_none_from_bucket_name('bucket2') == 'ID-2'

        cache.set_bucket_name_cache([buckets[1]])

        assert cache.get_bucket_id_or_none_from_bucket_name('bucket1') == 'ID-1'
        assert cache.get_bucket_id_or_none_from_bucket_name('bucket2') is None

    def test_remove_bucket_name(self, cache, buckets):
        cache.save_bucket(buckets[0])
        cache.save_bucket(buckets[1])

        cache.remove_bucket_name('bucket0')

        assert cache.get_bucket_id_or_none_from_bucket_name('bucket0') is None
        assert cache.get_bucket_name_or_none_from_bucket_id('ID-0') is None
        assert cache.get_bucket_id_or_none_from_bucket_name('bucket1') == 'ID-1'

        cache.remove_bucket_name('bucket0')  # removing a name that is not cached is a no-op
        assert cache.get_bucket_id_or_none_from_bucket_name('bucket1') == 'ID-1'

    def test_remove_bucket_id(self, cache, buckets):
        cache.save_bucket(buckets[0])
        cache.save_bucket(buckets[1])

        assert cache.remove_bucket_id('ID-0') == 'bucket0'

        assert cache.get_bucket_id_or_none_from_bucket_name('bucket0') is None
        assert cache.get_bucket_name_or_none_from_bucket_id('ID-0') is None
        assert cache.get_bucket_id_or_none_from_bucket_name('bucket1') == 'ID-1'
        assert cache.remove_bucket_id('ID-0') is None  # already gone: nothing to remove
        assert cache.remove_bucket_id('never-cached') is None

    def test_dummy_cache_remove_bucket_name(self, dummy_cache, buckets):
        dummy_cache.save_bucket(buckets[0])
        dummy_cache.remove_bucket_name('bucket0')
        assert dummy_cache.get_bucket_id_or_none_from_bucket_name('bucket0') is None
        assert dummy_cache.remove_bucket_id('ID-0') is None
