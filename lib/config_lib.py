# Copyright 2015 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Configuration options for various cbuildbot builders."""

from chromite.lib import constants
from chromite.utils import memoize


GS_PATH_DEFAULT = "default"  # Means gs://chromeos-image-archive/ + bot_id


class AttrDict(dict):
    """Dictionary with 'attribute' access.

    This is identical to a dictionary, except that string keys can be addressed
    as read-only attributes.
    """

    def __getattr__(self, name: str):
        """Support attribute-like access to each dict entry."""
        if name in self:
            return self[name]

        # Super class (dict) has no __getattr__ method, so use __getattribute__.
        return super().__getattribute__(name)


def DefaultSettings():
    # Enumeration of valid settings; any/all config settings must be in this.
    # All settings must be documented.
    return {
        # The name of the template we inherit settings from.
        "_template": None,
        # The name of the config.
        "name": None,
        # A list of boards to build.
        "boards": None,
        # This value defines what part of the Golden Eye UI is responsible for
        # displaying builds of this build config. The value is required, and
        # must be in ALL_DISPLAY_LABEL.
        # TODO: Make the value required after crbug.com/776955 is finished.
        "display_label": None,
        # The profile of the variant to set up and build.
        "profile": None,
        # This bot pushes changes to the overlays.
        "master": False,
        # If this bot triggers slave builds, this will contain a list of
        # slave config names.
        "slave_configs": None,
        # If False, this flag indicates that the CQ should not check whether
        # this bot passed or failed. Set this to False if you are setting up a
        # new bot. Once the bot is on the waterfall and is consistently green,
        # mark the builder as important=True.
        "important": True,
        # If True, build config should always be run as if --debug was set
        # on the cbuildbot command line. This is different from 'important'
        # and is usually correlated with tryjob build configs.
        "debug": False,
        # If True, use the debug instance of CIDB instead of prod.
        "debug_cidb": False,
        # Timeout for the build as a whole (in seconds).
        "build_timeout": (5 * 60 + 30) * 60,
        # Whether this is an internal build config.
        "internal": False,
        # Whether this is a branched build config. Used for pfq logic.
        "branch": False,
        # The name of the manifest to use. E.g., to use the buildtools manifest,
        # specify 'buildtools'.
        "manifest": constants.DEFAULT_MANIFEST,
        # emerge use flags to use while setting up the board, building packages,
        # making images, etc.
        "useflags": [],
        # Set the variable CHROMEOS_OFFICIAL for the build. Known to affect
        # parallel_emerge, cros_set_lsb_release, and chromeos_version.sh. See
        # bug chromium-os:14649
        "chromeos_official": False,
        # Use binary packages for build_packages and setup_board.
        "usepkg_build_packages": True,
        # Does this profile need to sync chrome?  If None, we guess based on
        # other factors.  If True/False, we always do that.
        "sync_chrome": None,
        # Wipe and replace chroot, but not source.
        "chroot_replace": True,
        # Uprevs the local ebuilds to build new changes since last stable.
        # build.  If master then also pushes these changes on success. Note that
        # we uprev on just about every bot config because it gives us a more
        # deterministic build system (the tradeoff being that some bots build
        # from source more frequently than if they never did an uprev). This way
        # the release/factory/etc... builders will pick up changes that devs
        # pushed before it runs, but after the correspoding PFQ bot ran (which
        # is what creates+uploads binpkgs).  The incremental bots are about the
        # only ones that don't uprev because they mimic the flow a developer
        # goes through on their own local systems.
        "uprev": True,
        # Select what overlays to look at for revving and prebuilts. This can be
        # any constants.VALID_OVERLAYS.
        "overlays": constants.PUBLIC_OVERLAYS,
        # Select what overlays to push at. This should be a subset of overlays
        # for the particular builder.  Must be None if not a master.  There
        # should only be one master bot pushing changes to each overlay per
        # branch.
        "push_overlays": None,
        # Uprev Chrome, values of 'tot', 'stable_release', or None.
        "chrome_rev": None,
        # Runs unittests for packages.
        "unittests": True,
        # If true, uploads artifacts for hw testing. Upload payloads for test
        # image if the image is built. If not, dev image is used and then base
        # image.
        "upload_hw_test_artifacts": True,
        # If true, uploads individual image tarballs.
        "upload_standalone_images": True,
        # Whether to run BuildConfigsExport stage. This stage generates build
        # configs (see crbug.com/974795 project). Only release builders should
        # run this stage.
        "run_build_configs_export": False,
        # List of patterns for portage packages for which stripped binpackages
        # should be uploaded to GS. The patterns are used to search for packages
        # via `equery list`.
        "upload_stripped_packages": [
            # Used by SimpleChrome workflow.
            "chromeos-base/chromeos-chrome",
            "sys-kernel/*kernel*",
        ],
        # Google Storage path to offload files to.
        #   None - No upload
        #   GS_PATH_DEFAULT - 'gs://chromeos-image-archive/' + bot_id
        #   value - Upload to explicit path
        "gs_path": GS_PATH_DEFAULT,
        # TODO(sosa): Deprecate binary.
        # Type of builder.  Check constants.VALID_BUILD_TYPES.
        "build_type": None,
        # Whether to schedule test suites by suite_scheduler. Generally only
        # True for "release" builders.
        "suite_scheduling": False,
        # The class name used to build this config.  See the modules in
        # cbuildbot / builders/*_builders.py for possible values.  This should
        # be the name in string form -- e.g. "simple_builders.SimpleBuilder" to
        # get the SimpleBuilder class in the simple_builders module.  If not
        # specified, we'll fallback to legacy probing behavior until everyone
        # has been converted (see the scripts/cbuildbot.py file for details).
        "builder_class_name": None,
        # List of images we want to build -- see `cros build-image --help`.
        "images": ["test"],
        # Whether to build a netboot image.
        "factory_install_netboot": True,
        # Whether to build the factory toolkit.
        "factory_toolkit": True,
        # Whether to build factory packages in BuildPackages.
        "factory": True,
        # Flag to control if all packages for the target are built. If disabled
        # and unittests are enabled, the unit tests and their dependencies
        # will still be built during the testing stage.
        "build_packages": True,
        # Tuple of specific packages we want to build.  Most configs won't
        # specify anything here and instead let build_packages calculate.
        "packages": [],
        # Do we push a final release image to chromeos-images.
        "push_image": False,
        # Do we upload debug symbols.
        "upload_symbols": False,
        # Run a stage that generates and uploads debug symbols.
        "debug_symbols": True,
        # Include *.debug files for debugging core files with gdb in debug.tgz.
        # These are very large. This option only has an effect if debug_symbols
        # and archive are set.
        "archive_build_debug": False,
        # Run a stage that archives build and test artifacts for developer
        # consumption.
        "archive": True,
        # Git repository URL for our manifests.
        #  https://chromium.googlesource.com/chromiumos/manifest
        #  https://chrome-internal.googlesource.com/chromeos/manifest-internal
        "manifest_repo_url": None,
        # Whether we are using the manifest_version repo that stores per-build
        # manifests.
        "manifest_version": False,
        # Use a different branch of the project manifest for the build.
        "manifest_branch": None,
        # Upload prebuilts for this build. Valid values are PUBLIC, PRIVATE, or
        # False.
        "prebuilts": False,
        # Use SDK as opposed to building the chroot from source.
        "use_sdk": True,
        # The description string to print out for config when user runs --list.
        "description": None,
        # Boolean that enables parameter --git-sync for upload_prebuilts.
        "git_sync": False,
        # If enabled, run the PatchChanges stage.  Enabled by default. Can be
        # overridden by the --nopatch flag.
        "postsync_patch": True,
        # Reexec into the buildroot after syncing.  Enabled by default.
        "postsync_reexec": True,
        # If specified, it is passed on to the PushImage script as
        # '--sign-types' commandline argument.  Must be either None or a list of
        # image types.
        "sign_types": None,
        # TODO(sosa): Collapse to one option.
        # ========== Dev installer prebuilts options =======================
        # Upload prebuilts for this build to this bucket. If it equals None the
        # default buckets are used.
        "binhost_bucket": None,
        # Parameter --key for upload_prebuilts. If it equals None, the default
        # values are used, which depend on the build type.
        "binhost_key": None,
        # Parameter --binhost-base-url for upload_prebuilts. If it equals None,
        # the default value is used.
        "binhost_base_url": None,
        # Enable rootfs verification on the image.
        "rootfs_verification": True,
        # ==================================================================
        # Workspace related options.
        # Which branch should WorkspaceSyncStage checkout, if run.
        "workspace_branch": None,
        # ==================================================================
        # The documentation associated with the config.
        "doc": None,
        # This is a LUCI Scheduler schedule string. Setting this will create
        # a LUCI Scheduler for this build on swarming (not buildbot).
        # See: https://goo.gl/VxSzFf
        "schedule": None,
        # This is the list of git repos which can trigger this build in
        # swarming. Implies that schedule is set, to "triggered".
        # The format is of the form:
        #   [ (<git repo url>, (<ref1>, <ref2>, …)),
        #    …]
        "triggered_gitiles": None,
        # If true, skip package retries in BuildPackages step.
        "nobuildretry": False,
    }


def GerritInstanceParameters(name, instance):
    param_names = [
        "_GOB_INSTANCE",
        "_GERRIT_INSTANCE",
        "_GOB_HOST",
        "_GERRIT_HOST",
        "_GOB_URL",
        "_GERRIT_URL",
    ]

    gob_instance = instance
    gerrit_instance = "%s-review" % instance
    gob_host = constants.GOB_HOST % gob_instance
    gerrit_host = constants.GOB_HOST % gerrit_instance
    gob_url = "https://%s" % gob_host
    gerrit_url = "https://%s" % gerrit_host

    params = [
        gob_instance,
        gerrit_instance,
        gob_host,
        gerrit_host,
        gob_url,
        gerrit_url,
    ]

    return {f"{name}{pn}": p for pn, p in zip(param_names, params)}


def DefaultSiteParameters():
    # Enumeration of valid site parameters; any/all site parameters must be
    # here. All site parameters should be documented.
    default_site_params = {}

    external_remote = "cros"
    internal_remote = "cros-internal"
    chromium_remote = "chromium"
    aosp_remote = "aosp"
    weave_remote = "weave"

    internal_change_prefix = "chrome-internal:"
    external_change_prefix = "chromium:"

    # Gerrit instance site parameters.
    default_site_params.update(GerritInstanceParameters("EXTERNAL", "chromium"))
    default_site_params.update(
        GerritInstanceParameters("INTERNAL", "chrome-internal")
    )

    default_site_params.update(
        # CrOS remotes specified in the manifests.
        EXTERNAL_REMOTE=external_remote,
        INTERNAL_REMOTE=internal_remote,
        # Prefix to distinguish internal and external changes. This is used
        # when a user specifies a patch with "-g", when generating a key for
        # a patch to use in our PatchCache, and when displaying a custom
        # string for the patch.
        INTERNAL_CHANGE_PREFIX=internal_change_prefix,
        EXTERNAL_CHANGE_PREFIX=external_change_prefix,
        CHANGE_PREFIX={
            external_remote: external_change_prefix,
            internal_remote: internal_change_prefix,
        },
        # List of remotes that are okay to include in the external manifest.
        EXTERNAL_REMOTES=(
            external_remote,
            chromium_remote,
            aosp_remote,
            weave_remote,
        ),
        # Additional parameters used to filter manifests, create modified
        # manifests, and to branch manifests.
        MANIFEST_VERSIONS_GOB_URL=(
            "%s/chromiumos/manifest-versions"
            % default_site_params["EXTERNAL_GOB_URL"]
        ),
        MANIFEST_VERSIONS_INT_GOB_URL=(
            "%s/chromeos/manifest-versions"
            % default_site_params["INTERNAL_GOB_URL"]
        ),
        MANIFEST_VERSIONS_GS_URL="gs://chromeos-manifest-versions",
        # Standard directories under buildroot for cloning these repos.
        EXTERNAL_MANIFEST_VERSIONS_PATH="manifest-versions",
        INTERNAL_MANIFEST_VERSIONS_PATH="manifest-versions-internal",
        # GS URL in which to archive build artifacts.
        ARCHIVE_URL="gs://chromeos-image-archive",
    )

    return default_site_params


@memoize.Memoize
def GetSiteParams():
    """Get the site parameter configs.

    This is the new, preferred method of accessing the site parameters, instead
    of SiteConfig.params.

    Returns:
        AttrDict of site parameters
    """
    site_params = AttrDict()
    site_params.update(DefaultSiteParameters())
    return site_params
