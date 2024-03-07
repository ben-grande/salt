"""
These only test the provider selection and verification logic, they do not init
any remotes.
"""

import logging
import os
import pathlib
import signal
import tempfile
import time

import pytest
from saltfactories.utils import random_string

import salt.ext.tornado.ioloop
import salt.fileserver.gitfs
import salt.utils.files
import salt.utils.gitfs
import salt.utils.path
import salt.utils.platform
import salt.utils.process
from salt.grains.core import get_machine_id
from salt.utils.immutabletypes import freeze
from salt.utils.verify import verify_env

try:
    import pwd
except ImportError:
    import salt.utils.win_functions

log = logging.getLogger(__name__)


def _get_user():
    """
    Get the user associated with the current process.
    """
    if salt.utils.platform.is_windows():
        return salt.utils.win_functions.get_current_user(with_domain=False)
    return pwd.getpwuid(os.getuid())[0]


@pytest.fixture(scope="module", autouse=True)
def _factory_root_dir(salt_factories):
    return salt_factories.root_dir.resolve()


@pytest.fixture(scope="module", autouse=True)
def _salt_master_factory_config_parent(salt_master_factory):
    return pathlib.PurePath(salt_master_factory.config["conf_file"]).parent


@pytest.fixture(scope="module", autouse=True)
def _salt_master_factory_config_path(salt_master_factory):
    return pathlib.PurePath(salt_master_factory.config["conf_file"]).parent.joinpath(
        "master"
    )


@pytest.fixture(scope="module", autouse=True)
def _salt_minion_factory_config_path(salt_minion_factory):
    return pathlib.PurePath(salt_minion_factory.config["conf_file"]).parent.joinpath(
        "minion"
    )


@pytest.fixture(scope="module", autouse=True)
def _create_old_tempdir(_factory_root_dir):
    return pathlib.Path(str(_factory_root_dir)).mkdir(exist_ok=True, parents=True)


## @pytest.fixture
## def get_tmp_dir(tmp_path):
##     dirpath = tmp_path / "git_test"
##     dirpath.mkdir(parents=True)
##     return dirpath
##
##     ## dirpath.cleanup()


def _clear_instance_map():
    try:
        del salt.utils.gitfs.GitFS.instance_map[
            salt.ext.tornado.ioloop.IOLoop.current()
        ]
    except KeyError:
        pass


class AdaptedConfigurationTestCaseMixin:

    @staticmethod
    def get_temp_config(config_for, _factory_root_dir, **config_overrides):

        rootdir = config_overrides.get("root_dir", str(_factory_root_dir))

        if not pathlib.Path(rootdir).exists():
            pathlib.Path(str(_factory_root_dir)).mkdir(exist_ok=True, parents=True)

        rootdir = config_overrides.get("root_dir", str(_factory_root_dir))
        conf_dir = config_overrides.pop(
            "conf_dir", str(pathlib.PurePath(rootdir).joinpath("conf"))
        )

        curr_user = _get_user()
        for key in ("cachedir", "pki_dir", "sock_dir"):
            if key not in config_overrides:
                config_overrides[key] = key
        if "log_file" not in config_overrides:
            config_overrides["log_file"] = f"logs/{config_for}.log".format()
        if "user" not in config_overrides:
            config_overrides["user"] = curr_user
        config_overrides["root_dir"] = rootdir

        cdict = AdaptedConfigurationTestCaseMixin.get_config(
            config_for,
            from_scratch=True,
        )

        if config_for in ("master", "client_config"):
            rdict = salt.config.apply_master_config(config_overrides, cdict)
        if config_for == "minion":
            minion_id = (
                config_overrides.get("id")
                or config_overrides.get("minion_id")
                or cdict.get("id")
                or cdict.get("minion_id")
                or random_string("temp-minion-")
            )
            config_overrides["minion_id"] = config_overrides["id"] = minion_id
            rdict = salt.config.apply_minion_config(
                config_overrides, cdict, cache_minion_id=False, minion_id=minion_id
            )

        verify_env(
            [
                pathlib.PurePath(rdict["pki_dir"]).joinpath("minions"),
                pathlib.PurePath(rdict["pki_dir"]).joinpath("minions_pre"),
                pathlib.PurePath(rdict["pki_dir"]).joinpath("minions_rejected"),
                pathlib.PurePath(rdict["pki_dir"]).joinpath("minions_denied"),
                pathlib.PurePath(rdict["cachedir"]).joinpath("jobs"),
                pathlib.PurePath(rdict["cachedir"]).joinpath("tokens"),
                pathlib.PurePath(rdict["root_dir"]).joinpath("cache", "tokens"),
                pathlib.PurePath(rdict["pki_dir"]).joinpath("accepted"),
                pathlib.PurePath(rdict["pki_dir"]).joinpath("rejected"),
                pathlib.PurePath(rdict["pki_dir"]).joinpath("pending"),
                pathlib.PurePath(rdict["log_file"]).parent,
                rdict["sock_dir"],
                conf_dir,
            ],
            curr_user,
            root_dir=rdict["root_dir"],
        )

        rdict["conf_file"] = pathlib.PurePath(conf_dir).joinpath(config_for)
        with salt.utils.files.fopen(rdict["conf_file"], "w") as wfh:
            salt.utils.yaml.safe_dump(rdict, wfh, default_flow_style=False)
        return rdict

    @staticmethod
    def get_config(
        config_for,
        from_scratch=False,
    ):
        if from_scratch:
            if config_for in ("master"):
                return salt.config.master_config(str(_salt_master_factory_config_path))
            elif config_for in ("minion"):
                return salt.config.minion_config(str(_salt_minion_factory_config_path))
            elif config_for == "client_config":
                return salt.config_client_config(str(_salt_master_factory_config_path))
        if config_for not in ("master", "minion", "client_config"):
            if config_for in ("master"):
                return freeze(
                    salt.config.master_config(str(_salt_master_factory_config_path))
                )
            elif config_for in ("minion"):
                return freeze(
                    salt.config.minion_config(str(_salt_minion_factory_config_path))
                )
            elif config_for == "client_config":
                return freeze(
                    salt.config.client_config(str(_salt_master_factory_config_path))
                )

        log.error(
            "Should not reach this section of code for get_config, missing support for input config_for %s",
            config_for,
        )

        # at least return master's config
        return freeze(salt.config.master_config(str(_salt_master_factory_config_path)))

    @property
    def config_dir(self):
        return str(_salt_master_factory_config_parent)

    def get_config_dir(self):
        log.warning("Use the config_dir attribute instead of calling get_config_dir()")
        return self.config_dir

    @staticmethod
    def get_config_file_path(filename):
        if filename == "master":
            return str(_salt_master_factory_config_path)

        if filename == "minion":
            return str(_salt_minion_factory_config_path)

        return str(_salt_master_factory_config_path)

    @property
    def master_opts(self):
        """
        Return the options used for the master
        """
        return self.get_config("master")

    @property
    def minion_opts(self):
        """
        Return the options used for the minion
        """
        return self.get_config("minion")

    @property
    def sub_minion_opts(self):
        """
        Return the options used for the sub_minion
        """
        return self.get_config("sub_minion")


class TestGitBase(AdaptedConfigurationTestCaseMixin):
    """
    mocked GitFS provider leveraging tmp_path
    """

    def __init__(
        self,
    ):
        ## self._tmp_dir = pathlib.Path(tmp_path / "git_test").mkdir(exist_ok=True, parents=True)
        ## tmp_name = str(self._tmp_dir)
        self._tmp_dir = tempfile.TemporaryDirectory()
        tmp_name = self._tmp_dir.name

        class MockedProvider(
            salt.utils.gitfs.GitProvider
        ):  # pylint: disable=abstract-method
            def __init__(
                self,
                opts,
                remote,
                per_remote_defaults,
                per_remote_only,
                override_params,
                cache_root,
                role="gitfs",
            ):
                self.provider = "mocked"
                self.fetched = False
                super().__init__(
                    opts,
                    remote,
                    per_remote_defaults,
                    per_remote_only,
                    override_params,
                    cache_root,
                    role,
                )

            def init_remote(self):
                self.gitdir = salt.utils.path.join(tmp_name, ".git")
                self.repo = True
                new = False
                return new

            def envs(self):
                return ["base"]

            def _fetch(self):
                self.fetched = True

        # Clear the instance map so that we make sure to create a new instance
        # for this test class.
        _clear_instance_map()

        git_providers = {
            "mocked": MockedProvider,
        }
        gitfs_remotes = ["file://repo1.git", {"file://repo2.git": [{"name": "repo2"}]}]

        self.opts = self.get_temp_config(
            "master",
            _factory_root_dir,
            gitfs_remotes=gitfs_remotes,
            verified_gitfs_provider="mocked",
        )
        self.main_class = salt.utils.gitfs.GitFS(
            self.opts,
            self.opts["gitfs_remotes"],
            per_remote_overrides=salt.fileserver.gitfs.PER_REMOTE_OVERRIDES,
            per_remote_only=salt.fileserver.gitfs.PER_REMOTE_ONLY,
            git_providers=git_providers,
        )

    # DGM TBD do we need this, look at removing
    def tearDown(self):
        # Providers are preserved with GitFS's instance_map
        for remote in self.main_class.remotes:
            remote.fetched = False
        del self.main_class
        ## self._tmp_dir.cleanup()


@pytest.fixture
def main_class(tmp_path):
    test_git_base = TestGitBase()
    yield test_git_base.main_class

    test_git_base.tearDown()


def test_update_all(main_class):
    main_class.update()
    assert len(main_class.remotes) == 2, "Wrong number of remotes"
    assert main_class.remotes[0].fetched
    assert main_class.remotes[1].fetched


def test_update_by_name(main_class):
    main_class.update("repo2")
    assert len(main_class.remotes) == 2, "Wrong number of remotes"
    assert not main_class.remotes[0].fetched
    assert main_class.remotes[1].fetched


def test_update_by_id_and_name(main_class):
    main_class.update([("file://repo1.git", None)])
    assert len(main_class.remotes) == 2, "Wrong number of remotes"
    assert main_class.remotes[0].fetched
    assert not main_class.remotes[1].fetched


def test_get_cachedir_basename(main_class):
    assert main_class.remotes[0].get_cache_basename() == "_"
    assert main_class.remotes[1].get_cache_basename() == "_"


def test_git_provider_mp_lock_and_clear_lock(main_class):
    """
    Check that lock is released after provider.lock()
    and that lock is released after provider.clear_lock()
    """
    provider = main_class.remotes[0]
    provider.lock()
    # check that lock has been released
    assert provider._master_lock.acquire(timeout=5)
    provider._master_lock.release()

    provider.clear_lock()
    # check that lock has been released
    assert provider._master_lock.acquire(timeout=5)
    provider._master_lock.release()


@pytest.mark.slow_test
@pytest.mark.timeout_unless_on_windows(120)
def test_git_provider_mp_lock_timeout(main_class):
    """
    Check that lock will time out if master lock is locked.
    """
    provider = main_class.remotes[0]
    # Hijack the lock so git provider is fooled into thinking another instance is doing somthing.
    assert provider._master_lock.acquire(timeout=5)
    try:
        # git provider should raise timeout error to avoid lock race conditions
        pytest.raises(TimeoutError, provider.lock)
    finally:
        provider._master_lock.release()


@pytest.mark.slow_test
@pytest.mark.timeout_unless_on_windows(120)
def test_git_provider_mp_clear_lock_timeout(main_class):
    """
    Check that clear lock will time out if master lock is locked.
    """
    provider = main_class.remotes[0]
    # Hijack the lock so git provider is fooled into thinking another instance is doing somthing.
    assert provider._master_lock.acquire(timeout=5)
    try:
        # git provider should raise timeout error to avoid lock race conditions
        pytest.raises(TimeoutError, provider.clear_lock)
    finally:
        provider._master_lock.release()


@pytest.mark.slow_test
@pytest.mark.timeout_unless_on_windows(120)
def test_git_provider_mp_gen_lock(main_class, caplog):
    """
    Check that gen_lock is obtains lock, and then releases, provider.lock()
    """
    # DGM try getting machine_identifier
    # get machine_identifier
    ## mach_id = salt.utils.files.get_machine_identifier()
    mach_id = get_machine_id().get("machine_id", "no_machine_id_available")
    cur_pid = os.getpid()

    test_msg1 = (
        f"Set update lock for gitfs remote 'file://repo1.git' on machine_id '{mach_id}'"
    )
    test_msg2 = "Attempting to remove 'update' lock for 'gitfs' remote 'file://repo1.git' due to lock_set1 'True' or lock_set2"
    test_msg3 = f"Removed update lock for gitfs remote 'file://repo1.git' on machine_id '{mach_id}'"

    provider = main_class.remotes[0]

    # loop seeing if the test can be made to mess up a lock/unlock sequence
    max_count = 10000
    count = 0
    while count < max_count:
        count = count + 1
        caplog.clear()
        with caplog.at_level(logging.DEBUG):
            provider.fetch()

        assert test_msg1 in caplog.text
        assert test_msg2 in caplog.text
        assert test_msg3 in caplog.text


@pytest.mark.slow_test
@pytest.mark.timeout_unless_on_windows(120)
def test_git_provider_mp_lock_dead_pid(main_class, caplog):
    """
    Check that lock obtains lock, if previous pid in lock file doesn't exist for same machine id
    """
    # DGM try getting machine_identifier
    # get machine_identifier
    ## mach_id = salt.utils.files.get_machine_identifier()
    mach_id = get_machine_id().get("machine_id", "no_machine_id_available")
    cur_pid = os.getpid()

    test_msg1 = (
        f"Set update lock for gitfs remote 'file://repo1.git' on machine_id '{mach_id}'"
    )
    test_msg3 = f"Removed update lock for gitfs remote 'file://repo1.git' on machine_id '{mach_id}'"

    provider = main_class.remotes[0]
    provider.lock()
    # check that lock has been released
    assert provider._master_lock.acquire(timeout=5)

    # get lock file and manipulate it for a dead pid
    file_name = provider._get_lock_file("update")
    dead_pid = 1234  # give it non-existant pid
    test_msg2 = (
        f"gitfs_global_lock is enabled and update lockfile {file_name} "
        "is present for gitfs remote 'file://repo1.git' on machine_id "
        f"{mach_id} with pid '{dead_pid}'. Process {dead_pid} obtained "
        f"the lock for machine_id {mach_id}, current machine_id {mach_id} "
        "but this process is not running. The update may have been "
        "interrupted.  Given this process is for the same machine the "
        "lock will be reallocated to new process"
    )

    # remove existing lock file and write fake lock file with bad pid
    assert pathlib.Path(file_name).is_file()
    pathlib.Path(file_name).unlink()

    try:
        # write lock file similar to salt/utils/gitfs.py
        fh_ = os.open(file_name, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        with os.fdopen(fh_, "wb"):
            # Write the lock file and close the filehandle
            os.write(fh_, salt.utils.stringutils.to_bytes(str(dead_pid)))
            os.write(fh_, salt.utils.stringutils.to_bytes("\n"))
            os.write(fh_, salt.utils.stringutils.to_bytes(str(mach_id)))
            os.write(fh_, salt.utils.stringutils.to_bytes("\n"))

    except OSError as exc:
        log.error(
            "Failed to write fake dead pid lock file %s, exception %s", file_name, exc
        )

    provider._master_lock.release()

    with caplog.at_level(logging.DEBUG):
        provider.lock()
        # check that lock has been released
        assert provider._master_lock.acquire(timeout=5)
        provider._master_lock.release()

    provider.clear_lock()
    # check that lock has been released
    assert provider._master_lock.acquire(timeout=5)
    provider._master_lock.release()

    assert test_msg1 in caplog.text
    assert test_msg2 in caplog.text
    assert test_msg3 in caplog.text


@pytest.mark.slow_test
@pytest.mark.timeout_unless_on_windows(120)
def test_git_provider_mp_lock_bad_machine(main_class, caplog):
    """
    Check that lock obtains lock, if previous pid in lock file doesn't exist for same machine id
    """
    # DGM try getting machine_identifier
    # get machine_identifier
    ## mach_id = salt.utils.files.get_machine_identifier()
    mach_id = get_machine_id().get("machine_id", "no_machine_id_available")
    cur_pid = os.getpid()

    provider = main_class.remotes[0]
    provider.lock()
    # check that lock has been released
    assert provider._master_lock.acquire(timeout=5)

    # get lock file and manipulate it for a dead pid
    file_name = provider._get_lock_file("update")
    bad_mach_id = "abcedf0123456789"  # give it non-existant pid

    test_msg1 = (
        f"gitfs_global_lock is enabled and update lockfile {file_name} "
        "is present for gitfs remote 'file://repo1.git' on machine_id "
        f"{mach_id} with pid '{cur_pid}'. Process {cur_pid} obtained "
        f"the lock for machine_id {bad_mach_id}, current machine_id {mach_id}"
    )
    test_msg2 = f"Removed update lock for gitfs remote 'file://repo1.git' on machine_id '{mach_id}'"

    # remove existing lock file and write fake lock file with bad pid
    assert pathlib.Path(file_name).is_file()
    pathlib.Path(file_name).unlink()

    try:
        # write lock file similar to salt/utils/gitfs.py
        fh_ = os.open(file_name, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        with os.fdopen(fh_, "wb"):
            # Write the lock file and close the filehandle
            os.write(fh_, salt.utils.stringutils.to_bytes(str(cur_pid)))
            os.write(fh_, salt.utils.stringutils.to_bytes("\n"))
            os.write(fh_, salt.utils.stringutils.to_bytes(str(bad_mach_id)))
            os.write(fh_, salt.utils.stringutils.to_bytes("\n"))

    except OSError as exc:
        log.error(
            "Failed to write fake dead pid lock file %s, exception %s", file_name, exc
        )

    provider._master_lock.release()

    with caplog.at_level(logging.DEBUG):
        provider.lock()
        # check that lock has been released
        assert provider._master_lock.acquire(timeout=5)
        provider._master_lock.release()

    provider.clear_lock()
    # check that lock has been released
    assert provider._master_lock.acquire(timeout=5)
    provider._master_lock.release()

    assert test_msg1 in caplog.text
    assert test_msg2 in caplog.text


class KillProcessTest(salt.utils.process.SignalHandlingProcess):
    """
    Test process for which to kill and check lock resources are cleaned up
    """

    def __init__(self, provider, **kwargs):
        super().__init__(**kwargs)
        self.provider = provider
        self.opts = provider.opts
        self.threads = {}

    def run(self):
        """
        Start the test process to kill
        """
        self.provider.lock()

        # check that lock has been released
        assert self.provider._master_lock.acquire(timeout=5)

        while True:
            tsleep = 1
            time.sleep(tsleep)  # give time for kill by sigterm

        log.debug("DGM kill_test_process exit")


@pytest.mark.slow_test
@pytest.mark.skip_unless_on_linux
def test_git_provider_sigterm_cleanup(main_class, caplog):
    """
    Start process which will obtain lock, and leave it locked
    then kill the process via SIGTERM and ensure locked resources are cleaned up
    """
    provider = main_class.remotes[0]

    with salt.utils.process.default_signals(signal.SIGINT, signal.SIGTERM):
        procmgr = salt.utils.process.ProcessManager(wait_for_kill=1)
        proc = procmgr.add_process(KillProcessTest, args=(provider,), name="test_kill")

    while not proc.is_alive():
        time.sleep(1)  # give some time for it to be started

    procmgr.run()

    # child process should be alive
    file_name = provider._get_lock_file("update")

    assert pathlib.Path(file_name).exists()
    assert pathlib.Path(file_name).is_file()

    procmgr.terminate()  # sends a SIGTERM

    time.sleep(1)  # give some time for it to terminate

    assert not proc.is_alive()
    assert not pathlib.Path(file_name).exists()
