#!/usr/bin/env python3

# Copyright (C) 2017 John Koelndorfer
#
# This file is part of mccdl.
#
# mccdl is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

# mccdl is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with mccdl.  If not, see <http://www.gnu.org/licenses/>.

import argparse
from collections import namedtuple
from distutils.dir_util import copy_tree
import errno
from functools import reduce
import hashlib
import json
import logging
import os
from urllib.parse import unquote as urlunquote, urljoin as _urljoin
import re
import shutil
import sys
import textwrap
import zipfile

import appdirs
from bs4 import BeautifulSoup
import requests


CurseForgeModPackFile = namedtuple("CurseForgeModPackFile", ("project_id", "file_id", "required"))
CurseForgeFileListing = namedtuple("CurseForgeFileListing", ("project_id", "file_id", "game_version"))


def logger(obj):
    """
    Returns a logger suitable for use by the passed in object.
    """
    return logging.getLogger(".".join(["mccdl", obj.__class__.__name__]))


def urljoin(base, *parts):
    """
    URL join function that makes more sense than Python's standard library version.
    """
    return reduce(lambda base, part: _urljoin(base + "/", str(part).lstrip("/")), parts, base)


class CurseForgeClient:
    CURSE_HOSTNAME = "minecraft.curseforge.com"
    CURSE_BASE_URL = "http://" + CURSE_HOSTNAME
    DEFAULT_CACHE_DIR = appdirs.user_cache_dir("mccdl")

    def __init__(self, instance_manager, downloader, unpacker):
        self.downloader = downloader
        self.instance_manager = instance_manager
        self.logger = logger(self)
        self.unpacker = unpacker

    def install_modpack(self, project_id, file_id, instance_name):
        self._setup_modpack("install", project_id, file_id, instance_name)

    def upgrade_modpack(self, project_id, file_id, instance_name):
        self._setup_modpack("upgrade", project_id, file_id, instance_name)

    def project(self, project_id):
        return CurseForgeProject(self, project_id)

    def url_for(self, *path):
        return urljoin(self.CURSE_BASE_URL, *path)

    def _setup_modpack(self, mode, project_id, file_id, instance_name):
        assert mode in ("install", "upgrade")
        action = {"install": "Installing", "upgrade": "Upgrading"}.get(mode)

        self.logger.info("%s modpack %s in instance %s, file ID %s",
                         action, str(project_id), instance_name, str(file_id))

        project = self.project(project_id)
        modpack_extract_dir = project.download_and_unpack_file(file_id)
        modpack = CurseForgeModPack(modpack_extract_dir)

        instance = self.instance_manager.instance(instance_name)
        setup_method = {"install": instance.create, "upgrade": instance.upgrade}.get(mode)
        setup_args = [modpack.minecraft_version, modpack.forge_version]
        if mode == "install":
            project_icon = project.download_icon()
            setup_args.append(project_icon)
        setup_method(*setup_args)

        for modpack_file in modpack.files():
            self.project(modpack_file.project_id).download_file(
                modpack_file.file_id, instance.mods_directory, game_version=modpack.minecraft_version
            )
        self.logger.info("Installing modpack overrides")
        modpack.install_overrides(instance.minecraft_directory)

    def url_to_project_and_file(self, url):
        # Each entry in this list contains a regular expression matching a Curse
        # project URL and two integers. The integers are group numbers for the previous
        # regular expression. The first integer is required and is the capture group of
        # project ID of the modpack. The second integer may be None and is the
        # capture group of the file ID of the modpack.
        url_regexes = [
            ["/projects/([^/]*)(/files/([0-9]+)/)?", 1, 3],
            ["/modpacks/minecraft/([0-9]+)-", 1, None]
        ]
        project_id = None
        file_id = None
        for regex, project_group_nr, file_group_nr in url_regexes:
            match = re.search(regex, url)
            if match is None:
                continue
            project_id = match.group(project_group_nr)
            if file_group_nr is not None:
                file_id = match.group(file_group_nr)
        if project_id is None:
            raise InvalidCurseModpackUrlError("{} is not a valid Minecraft CurseForge URL".format(url))
        file_id = file_id or "latest"
        return (project_id, file_id)


class CurseForgeProject:
    def __init__(self, client, project_id):
        self._client = client
        self.logger = logger(self)
        self.project_id = project_id

    def download_and_unpack_file(self, file_id):
        archive_path = self.download_file(file_id)
        unpack_directory = self._client.unpacker.unpack(archive_path)
        return unpack_directory

    def download_file(self, file_id, destination=None, game_version=None):
        self.logger.info("Fetching project %s, file %s", str(self.project_id), str(file_id))
        try:
            file_path = self._client.downloader.download(self.file_url(file_id), destination)
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 404:
                # A file disappeared on Curse, or maybe the modpack author screwed up.
                # Let's try to get the next available file.
                next_file = self._next_file_after(file_id, game_version)
                self.logger.warn("Could not find file %s for project %s, getting file %d instead",
                                 file_id, self.project_id, next_file.file_id)
                file_path = self._client.downloader.download(self.file_url(next_file.file_id), destination)
            else:
                raise e
        return file_path

    def download_icon(self):
        response = requests.get(self.url_for())
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        icon_url = soup.findChild("div", attrs={"class": "avatar-wrapper"}).findChild("img").get("src")

        return self._client.downloader.download(icon_url)

    def _files(self, game_version=None):
        response = requests.get(self.url_for("files"))
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        # All file links share the same class overflow-tip.
        #
        # These hrefs are something like /projects/$project_name/files/$file_id
        file_elements = soup.find_all("tr", attrs={"class": "project-file-list-item"})
        files = list()
        for fe in file_elements:
            file_link = fe.findChild("a", attrs={"class": "overflow-tip"}).get("href")
            file_id = int(file_link.split("/")[-1])
            file_game_version = fe.findChild("span", attrs={"class": "version-label"}).text.strip()
            files.append(CurseForgeFileListing(self.project_id, file_id, file_game_version))

        if game_version is not None:
            files_matching_version = [f for f in files if f.game_version == game_version]
        else:
            files_matching_version = files

        self.logger.debug(
            "Project %s has files: %s", self.project_id,
            ", ".join((str(i.file_id) for i in files_matching_version))
        )
        return files_matching_version

    def file_url(self, file_id):
        url_parts = ["files", file_id]
        if file_id != "latest":
            url_parts.append("download")
        url = self.url_for(*url_parts)
        self.logger.debug("URL for project %s, file %s is %s", self.project_id, file_id, url)
        return url

    def _next_file_after(self, file_id, game_version=None):
        file_id = int(file_id)
        file_id_list = self._files(game_version)
        return next(filter(lambda i: i.file_id > file_id, sorted(file_id_list)))

    def url_for(self, *path):
        return self._client.url_for("projects", self.project_id, *path)


class CurseForgeDownloadUnpacker:
    def __init__(self, unpack_dir):
        self.logger = logger(self)
        self.unpack_dir = unpack_dir

    def unpack(self, archive_path):
        self.logger.debug("Unpacking archive %s", archive_path)
        unpack_destination = self._unpack_destination(archive_path)
        try:
            shutil.rmtree(unpack_destination)
        except OSError as e:
            if e.errno != errno.ENOENT:
                raise e
        zipf = zipfile.ZipFile(str(archive_path))
        zipf.extractall(unpack_destination)
        self.logger.debug("Unpacked archive to %s", unpack_destination)

        return unpack_destination

    def _unpack_destination(self, archive_path):
        return os.path.join(self.unpack_dir, os.path.basename(archive_path))


class CurseForgeModPack:
    def __init__(self, unpack_directory):
        self.unpack_directory = unpack_directory
        with open(os.path.join(self.unpack_directory, "manifest.json"), "r") as f:
            self.manifest = json.loads(f.read())

    def files(self):
        for i in self.manifest["files"]:
            yield CurseForgeModPackFile(i["projectID"], i["fileID"], i["required"])

    def install_overrides(self, destination):
        # FIXME: distutils.dir_util.copy_tree seems to keep some internal state when it does its copy.
        #
        # If the destination directory disappears, copy_tree will not recreate missing path
        # components.
        #
        # In practice this should not be an issue since our script will execute once to install a
        # modpack, then exit.
        copy_tree(os.path.join(self.unpack_directory, self.manifest["overrides"]), destination)

    @property
    def forge_version(self):
        # TODO: Make this less brittle.
        #
        # The Forge modloader ID looks like "forge-12.18.3.2254", so strip off the
        # leading "forge-".
        return self.manifest["minecraft"]["modLoaders"][0]["id"].replace("forge-", "")

    @property
    def minecraft_version(self):
        return self.manifest["minecraft"]["version"]


class CachingDownloader:
    def __init__(self, cache_dir):
        self.cache_dir = cache_dir
        self.logger = logger(self)

    def download(self, url, destination=None):
        url_cache_path = self._path_for_url(url)
        self.logger.debug("Cache directory for %s is %s", url, url_cache_path)
        cached_file_path = None
        if os.path.exists(url_cache_path):
            self.logger.debug("Cache directory for %s already exists", url)
            cached_dir_content = os.listdir(url_cache_path)
            cached_file_path = (os.path.join(url_cache_path, cached_dir_content[0])) if cached_dir_content else None

        if cached_file_path is None:
            self.logger.debug("No cached download for %s, downloading", url)
            cached_file_path = self._download(url)

        if destination is not None:
            self.logger.debug("Copying cached file %s to %s", cached_file_path, destination)
            destination = destination
            self._mkdir_p(os.path.dirname(destination))
            shutil.copy(cached_file_path, destination)
            download_destination = destination
        else:
            download_destination = cached_file_path

        return download_destination

    def _download(self, url):
        url_cache_path = self._path_for_url(url)

        response = requests.get(url, stream=True)
        response.raise_for_status()
        download_destination = self._download_destination(url_cache_path, response.url)

        self._mkdir_p(os.path.dirname(download_destination))

        with open(download_destination, "wb") as f:
            for buf in response.iter_content(1024):
                f.write(buf)

        return download_destination

    def _mkdir_p(self, path):
        try:
            os.makedirs(path)
        except OSError as e:
            if not e.errno == errno.EEXIST:
                raise e

    def _url_digest(self, url):
        return hashlib.sha256(url.encode("utf-8")).hexdigest()

    def _path_for_url(self, url):
        return os.path.join(self.cache_dir, self._url_digest(url))

    @classmethod
    def _download_filename(cls, response_url):
        return urlunquote(response_url.split("/")[-1])

    def _download_destination(self, dir_path, url):
        return os.path.join(dir_path, self._download_filename(url))


class MccdlCommandLineApplication:
    def __init__(self):
        self.argparser = argparse.ArgumentParser()
        self.configure_argparser()
        self.logger = logger(self)

    def configure_argparser(self):
        a = self.argparser
        a.add_argument(
            "-c", "--cache-directory", type=str, default=str(CurseForgeClient.DEFAULT_CACHE_DIR),
            help="Path to directory to cache mccdl files. Defaults to %(default)s."
        )
        a.add_argument(
            "-l", "--log-level", type=str, default="info",
            choices=("debug", "info", "warning", "error", "critical"),
            help="Log level to use  for this run. Defaults to %(default)s."
        )
        a.add_argument(
            "--upgrade", action="store_true", default=False,
            help="If specified, allow upgrading an existing modpack instance."
        )
        a.add_argument(
            "--multimc-directory", type=str, default=appdirs.user_data_dir("multimc5"),
            help="Path to the MultiMC directory. Defaults to %(default)s."
        )
        a.add_argument(
            "modpack_url", type=str,
            help="Link to the modpack on Minecraft CurseForge."
        )
        a.add_argument(
            "instance_name", type=str,
            help="Name of the MultiMC instance to create."
        )

    def configure_logging(self, log_level):
        logging.basicConfig()
        logger = logging.getLogger("mccdl")
        logger.setLevel(getattr(logging, log_level.upper()))

    def make_curseforge_client(self, args):
        cache_dir = args.cache_directory
        downloader = CachingDownloader(os.path.join(cache_dir, "download"))
        unpacker = CurseForgeDownloadUnpacker(os.path.join(cache_dir, "unpack"))
        instance_manager = MultiMcInstanceManager(args.multimc_directory, downloader)

        return CurseForgeClient(instance_manager, downloader, unpacker)

    def run(self, argv):
        args = self.argparser.parse_args(argv)
        self.configure_logging(args.log_level)
        c = self.make_curseforge_client(args)

        action_method = c.upgrade_modpack if args.upgrade else c.install_modpack
        project_id, file_id = c.url_to_project_and_file(args.modpack_url)
        action_method(project_id, file_id, args.instance_name)
        self.logger.info("Done installing modpack %s as instance %s", args.modpack_url, args.instance_name)


class MultiMcInstanceManager:
    def __init__(self, multimc_directory, downloader):
        self.multimc_directory = multimc_directory
        self.downloader = downloader

    def create(self, instance_name, minecraft_version, forge_version):
        instance = self.instance(instance_name)
        instance.create(minecraft_version, forge_version)

        return instance

    def instance(self, name):
        return MultiMcInstance(self._instance_dir(name), name, self)

    def _instance_dir(self, instance_name):
        return os.path.join(self.multimc_directory, "instances",  instance_name)


class MultiMcInstance:
    MULTIMC_FORGE_CONFIGURATION_SITE = "https://v1.meta.multimc.org/net.minecraftforge"

    def __init__(self, directory, name, instance_manager):
        self.directory = directory
        self.logger = logger(self)
        self.name = name
        self.instance_manager = instance_manager

    def configure(self, minecraft_version, forge_version, icon_key=None):
        self._configure_instance_base(minecraft_version, icon_key)
        self._configure_instance_forge(minecraft_version, forge_version)

    def create(self, minecraft_version, forge_version, icon_path=None):
        self.logger.info("Creating MultiMC instance %s, Minecraft version %s, Forge version %s",
                         self.name, minecraft_version, forge_version)
        if os.path.exists(self.directory):
            errmsg = "MultiMC instance {} already exists".format(self.name)
            raise MultiMcInstanceExistsError(errmsg)
        os.makedirs(self.mods_directory)

        multimc_icon_key = None
        if icon_path is not None:
            multimc_icon_filename = "mccdl_" + os.path.basename(icon_path)
            multimc_icon_key = os.path.splitext(multimc_icon_filename)[0]
            shutil.copyfile(
                icon_path, os.path.join(self.instance_manager.multimc_directory, "icons", multimc_icon_filename)
            )
        self.configure(minecraft_version, forge_version, icon_key=multimc_icon_key)

    def upgrade(self, minecraft_version, forge_version):
        try:
            shutil.rmtree(self.mods_directory)
        except FileNotFoundError:
            pass
        os.makedirs(self.mods_directory)

        self.configure(minecraft_version, forge_version)

    def _apply_instance_options(self, options={}):
        with open(self.instance_cfg, "r+") as f:
            f.seek(0, os.SEEK_SET)
            new_instance_cfg = f.read()
            f.seek(0, os.SEEK_SET)
            for k, v in options.items():
                new_instance_cfg = re.sub("({}=)[^\r\n]*".format(re.escape(k)),
                                          r"\g<1>" + v, new_instance_cfg)
            f.write(new_instance_cfg)
            f.truncate()

    def _configure_instance_base(self, minecraft_version, icon_key=None):
        if not os.path.exists(self.instance_cfg):
            self._set_default_instance_cfg()
        instance_options = {
            "IntendedVersion": minecraft_version
        }
        if icon_key is not None:
            instance_options["iconKey"] = icon_key
        self._apply_instance_options(instance_options)

    def _configure_instance_forge(self, minecraft_version, forge_version):
        self.logger.debug("Configuring MultiMC instance Forge")
        patches_dir = os.path.join(self.directory, "patches")
        self.instance_manager.downloader.download(
            self._forge_config_url(forge_version),
            os.path.join(patches_dir, "net.minecraftforge.json")
        )

    def _forge_config_url(self, forge_version):
        forge_config_filename = "{}.json".format(forge_version)
        return urljoin(self.MULTIMC_FORGE_CONFIGURATION_SITE, forge_config_filename)

    def _set_default_instance_cfg(self):
        instance_cfg_content = textwrap.dedent("""
            InstanceType=OneSix
            IntendedVersion=
            iconKey=default
            name={instance_name}
        """).format(instance_name=self.name).strip()
        self.logger.debug("Wrote instance configuration to %s", self.instance_cfg)
        with open(self.instance_cfg, "w") as f:
            f.write(instance_cfg_content)

    @property
    def minecraft_directory(self):
        return os.path.join(self.directory, "minecraft")

    @property
    def mods_directory(self):
        return os.path.join(self.minecraft_directory, "mods")

    @property
    def instance_cfg(self):
        return os.path.join(self.directory, "instance.cfg")


class MccdlError(Exception):
    """
    Base class for exceptions raised by mccdl.
    """


class InvalidCurseModpackUrlError(MccdlError):
    """
    Exception that is raised when the user provides an invalid Minecraft CurseForge
    project URL.
    """


class MultiMcInstanceExistsError(MccdlError):
    """
    Exception raised when a user tries to create a MultiMC instance that already exists.
    """


if __name__ == "__main__":
    MccdlCommandLineApplication().run(sys.argv[1:])
