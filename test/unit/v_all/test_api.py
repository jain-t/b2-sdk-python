######################################################################
#
# File: test/unit/v_all/test_api.py
#
# Copyright 2021 Backblaze Inc. All Rights Reserved.
#
# License https://www.backblaze.com/using_b2_code.html
#
######################################################################
from __future__ import annotations

import apiver_deps
import pytest
from apiver_deps import (
    AuthInfoCache,
    B2Api,
    B2HttpApiConfig,
    B2Session,
    Bucket,
    EncryptionMode,
    EncryptionSetting,
    InMemoryAccountInfo,
    InMemoryCache,
    RawSimulator,
    SqliteAccountInfo,
)
from apiver_deps_exception import BucketIdNotFound, NonExistentBucket

from ..test_base import TestBase


class DummyA:
    def __init__(self, *args, **kwargs):
        pass


class DummyB:
    def __init__(self, *args, **kwargs):
        pass


class TestServices:
    @pytest.mark.apiver(from_ver=2)
    @pytest.mark.parametrize(
        ('kwargs', '_raw_api_class'),
        [
            [
                {
                    'max_upload_workers': 1,
                    'max_copy_workers': 2,
                    'max_download_workers': 3,
                    'save_to_buffer_size': 4,
                    'check_download_hash': False,
                    'max_download_streams_per_file': 5,
                },
                DummyA,
            ],
            [
                {
                    'max_upload_workers': 2,
                    'max_copy_workers': 3,
                    'max_download_workers': 4,
                    'save_to_buffer_size': 5,
                    'check_download_hash': True,
                    'max_download_streams_per_file': 6,
                },
                DummyB,
            ],
        ],
    )
    def test_api_initialization(self, kwargs, _raw_api_class):
        self.account_info = InMemoryAccountInfo()
        self.cache = InMemoryCache()

        api_config = B2HttpApiConfig(_raw_api_class=_raw_api_class)

        self.api = B2Api(self.account_info, self.cache, api_config=api_config, **kwargs)

        assert isinstance(self.api.session, B2Session)  # ensure correct apiver session is used

        assert self.api.account_info is self.account_info
        assert self.api.api_config is api_config
        assert self.api.cache is self.cache

        assert self.api.session.account_info is self.account_info
        assert self.api.session.cache is self.cache
        assert isinstance(self.api.session.raw_api, _raw_api_class)

        assert isinstance(self.api.file_version_factory, B2Api.FILE_VERSION_FACTORY_CLASS)
        assert isinstance(
            self.api.download_version_factory,
            B2Api.DOWNLOAD_VERSION_FACTORY_CLASS,
        )

        services = self.api.services
        assert isinstance(services, B2Api.SERVICES_CLASS)

        # max copy/upload/download workers could only be verified with mocking

        download_manager = services.download_manager
        assert isinstance(download_manager, services.DOWNLOAD_MANAGER_CLASS)

        assert download_manager.write_buffer_size == kwargs['save_to_buffer_size']
        assert download_manager.check_hash == kwargs['check_download_hash']
        assert download_manager.strategies[0].max_streams == kwargs['max_download_streams_per_file']


class TestApi(TestBase):
    def setUp(self):
        self.account_info = InMemoryAccountInfo()
        self.cache = InMemoryCache()
        self.api = B2Api(
            self.account_info, self.cache, api_config=B2HttpApiConfig(_raw_api_class=RawSimulator)
        )
        self.raw_api = self.api.session.raw_api
        (self.application_key_id, self.master_key) = self.raw_api.create_account()

    def _authorize_account(self):
        self.api.authorize_account(
            realm='production',
            application_key_id=self.application_key_id,
            application_key=self.master_key,
        )

    @pytest.mark.apiver(to_ver=1)
    def test_get_bucket_by_id_up_to_v1(self):
        bucket = self.api.get_bucket_by_id("this id doesn't even exist")
        assert bucket.id_ == "this id doesn't even exist"
        for att_name, att_value in [
            ('name', None),
            ('type_', None),
            ('bucket_info', {}),
            ('cors_rules', []),
            ('lifecycle_rules', []),
            ('revision', None),
            ('bucket_dict', {}),
            ('options_set', set()),
            ('default_server_side_encryption', EncryptionSetting(EncryptionMode.UNKNOWN)),
        ]:
            with self.subTest(att_name=att_name):
                assert getattr(bucket, att_name) == att_value, att_name

    @pytest.mark.apiver(from_ver=2)
    def test_get_bucket_by_id_v2(self):
        self._authorize_account()
        with pytest.raises(BucketIdNotFound):
            self.api.get_bucket_by_id("this id doesn't even exist")
        created_bucket = self.api.create_bucket('bucket1', 'allPrivate')
        read_bucket = self.api.get_bucket_by_id(created_bucket.id_)
        assert created_bucket.id_ == read_bucket.id_
        self.cache.save_bucket(Bucket(api=self.api, name='bucket_name', id_='bucket_id'))
        read_bucket = self.api.get_bucket_by_id('bucket_id')
        assert read_bucket.name == 'bucket_name'

    def test_get_download_url_for_file_name(self):
        self._authorize_account()

        download_url = self.api.get_download_url_for_file_name('bucket1', 'some-file.txt')

        assert download_url == 'http://download.example.com/file/bucket1/some-file.txt'

    def test_get_download_url_for_fileid(self):
        self._authorize_account()

        download_url = self.api.get_download_url_for_fileid('file-id')

        if apiver_deps.V >= 3:
            exp_url = 'http://download.example.com/b2api/v4/b2_download_file_by_id?fileId=file-id'
        else:
            exp_url = 'http://download.example.com/b2api/v3/b2_download_file_by_id?fileId=file-id'

        assert download_url == exp_url


def test_recreated_bucket_resolves_to_new_id(tmp_path):
    # Delete a bucket and recreate it under the same name, then look it up by name.
    # With the CLI's setup (SqliteAccountInfo behind AuthInfoCache) the cache used to
    # keep the old id, and every call on the bucket failed with bad_bucket_id
    # (Backblaze/B2_Command_Line_Tool#567).
    account_info = SqliteAccountInfo(file_name=str(tmp_path / 'account_info'))
    api = B2Api(
        account_info,
        AuthInfoCache(account_info),
        api_config=B2HttpApiConfig(_raw_api_class=RawSimulator),
    )
    application_key_id, master_key = api.session.raw_api.create_account()
    api.authorize_account(
        realm='production', application_key_id=application_key_id, application_key=master_key
    )

    old_bucket = api.create_bucket('bucket1', 'allPrivate')
    assert api.get_bucket_by_name('bucket1').id_ == old_bucket.id_  # fills the name -> id cache
    api.delete_bucket(old_bucket)
    new_bucket = api.create_bucket('bucket1', 'allPrivate')
    assert new_bucket.id_ != old_bucket.id_

    assert api.get_bucket_by_name('bucket1').id_ == new_bucket.id_
    assert account_info.list_bucket_names_ids() == [('bucket1', new_bucket.id_)]
    if apiver_deps.V >= 2:
        # the stale id is gone from the cache, so the lookup reaches the server and fails
        with pytest.raises(BucketIdNotFound):
            api.get_bucket_by_id(old_bucket.id_)
    account_info.close()


def _sqlite_cached_api(tmp_path):
    account_info = SqliteAccountInfo(file_name=str(tmp_path / 'account_info'))
    api = B2Api(
        account_info,
        AuthInfoCache(account_info),
        api_config=B2HttpApiConfig(_raw_api_class=RawSimulator),
    )
    application_key_id, master_key = api.session.raw_api.create_account()
    api.authorize_account(
        realm='production', application_key_id=application_key_id, application_key=master_key
    )
    return api, account_info, application_key_id, master_key


def test_bucket_recreated_elsewhere_is_resolved_after_one_failure(tmp_path):
    # The delete and the recreate happen outside this client's cache (web UI, another
    # machine, CloudFormation). The first call on the stale id must still fail, but the
    # stale entry is dropped, so the next lookup by name gets the new id.
    api, account_info, application_key_id, master_key = _sqlite_cached_api(tmp_path)
    elsewhere = _api_elsewhere(api, application_key_id, master_key)

    old_bucket = api.create_bucket('bucket1', 'allPrivate')
    assert api.get_bucket_by_name('bucket1').id_ == old_bucket.id_  # fills this client's cache

    elsewhere.delete_bucket(elsewhere.get_bucket_by_name('bucket1'))
    new_bucket = elsewhere.create_bucket('bucket1', 'allPrivate')
    assert new_bucket.id_ != old_bucket.id_

    stale_bucket = api.get_bucket_by_name('bucket1')
    assert stale_bucket.id_ == old_bucket.id_  # cache hit; nothing has told this client yet

    with pytest.raises(BucketIdNotFound):  # the server answers bad_bucket_id
        list(stale_bucket.ls())

    assert account_info.get_bucket_id_or_none_from_bucket_name('bucket1') is None
    assert api.get_bucket_by_name('bucket1').id_ == new_bucket.id_
    account_info.close()


def test_delete_bucket_forgets_cached_name(tmp_path):
    api, account_info, _, _ = _sqlite_cached_api(tmp_path)
    bucket = api.create_bucket('bucket1', 'allPrivate')
    assert account_info.get_bucket_id_or_none_from_bucket_name('bucket1') == bucket.id_

    api.delete_bucket(bucket)

    assert account_info.get_bucket_id_or_none_from_bucket_name('bucket1') is None
    with pytest.raises(NonExistentBucket):
        api.get_bucket_by_name('bucket1')
    account_info.close()


def _api_elsewhere(api, application_key_id, master_key):
    """Another client of the same (simulated) server, with its own cache: a stand-in for
    another machine, the web UI or an infrastructure tool."""
    elsewhere = B2Api(
        InMemoryAccountInfo(),
        InMemoryCache(),
        api_config=B2HttpApiConfig(_raw_api_class=RawSimulator),
    )
    elsewhere.session.raw_api = api.session.raw_api
    elsewhere.authorize_account(
        realm='production', application_key_id=application_key_id, application_key=master_key
    )
    return elsewhere


def test_get_fresh_state_of_bucket_recreated_elsewhere_forgets_stale_id(tmp_path):
    # b2_list_buckets with a dead bucket id answers with an empty list rather than an error,
    # so this path never reaches the session's error handling: it has to evict on its own.
    api, account_info, application_key_id, master_key = _sqlite_cached_api(tmp_path)
    elsewhere = _api_elsewhere(api, application_key_id, master_key)

    api.create_bucket('bucket1', 'allPrivate')
    stale_bucket = api.get_bucket_by_name('bucket1')
    elsewhere.delete_bucket(elsewhere.get_bucket_by_name('bucket1'))
    new_bucket = elsewhere.create_bucket('bucket1', 'allPrivate')

    with pytest.raises(BucketIdNotFound):
        stale_bucket.get_fresh_state()

    assert account_info.get_bucket_id_or_none_from_bucket_name('bucket1') is None
    assert api.get_bucket_by_name('bucket1').id_ == new_bucket.id_
    account_info.close()


def test_list_buckets_by_name_of_bucket_deleted_elsewhere_forgets_cached_id(tmp_path):
    api, account_info, application_key_id, master_key = _sqlite_cached_api(tmp_path)
    elsewhere = _api_elsewhere(api, application_key_id, master_key)

    bucket = api.create_bucket('bucket1', 'allPrivate')
    assert api.get_bucket_by_name('bucket1').id_ == bucket.id_
    elsewhere.delete_bucket(elsewhere.get_bucket_by_name('bucket1'))  # deleted, not recreated

    assert api.list_buckets(bucket_name='bucket1') == []  # what `b2 bucket get` does

    assert account_info.get_bucket_id_or_none_from_bucket_name('bucket1') is None
    with pytest.raises(NonExistentBucket):
        api.get_bucket_by_name('bucket1')
    account_info.close()
