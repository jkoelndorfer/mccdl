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

from unittest import mock

import pytest

import mccdl


@pytest.fixture
def curseforge_client(multimc_instance_manager):
    downloader = mock.MagicMock(spec=mccdl.CachingDownloader)
    unpacker = mock.MagicMock(spec=mccdl.CurseForgeDownloadUnpacker)

    return mccdl.CurseForgeClient(multimc_instance_manager, downloader, unpacker)


@pytest.fixture
def modpack(modpack_file_list):
    modpack = mock.MagicMock(spec=mccdl.CurseForgeModPack)
    modpack.files = mock.MagicMock(return_value=modpack_file_list)
    type(modpack).minecraft_version = mock.PropertyMock(return_value="1.10.2")
    type(modpack).forge_version = mock.PropertyMock(return_value="1.10.2-12.18.3.2185")
    return modpack


@pytest.fixture
def modpack_file_list():
    return [
        mccdl.CurseForgeModPackFile(*i) for i in [
            (100, 1001, True),
            (200, 2461, True),
            (300, 1252, False)
        ]
    ]


@pytest.fixture
def multimc_instance():
    instance = mock.MagicMock(spec=mccdl.MultiMcInstance)
    type(instance).minecraft_directory = "/home/user/.local/share/multimc5/instances/instance/minecraft"
    type(instance).mods_directory = "/home/user/.local/share/multimc5/instances/instance/minecraft/mods"
    return instance


@pytest.fixture
def multimc_instance_manager(multimc_instance):
    instance_manager = mock.MagicMock(spec=mccdl.MultiMcInstanceManager)
    instance_manager.instance = mock.MagicMock(return_value=multimc_instance)
    return instance_manager


@pytest.fixture
def project():
    project = mock.MagicMock()
    project.download_icon = mock.MagicMock(return_value="/home/user/.cache/mccdl/download/icon.png")
    project.download_and_unpack_file = mock.MagicMock(return_value="/home/user/.cache/mccdl/unpack/file")
    return project


@pytest.fixture(params=[
    (1, 1, "FirstModPack"),
    (2, 2, "SecondModPack"),
    (1000, "latest", "mccdlPack")
])
def pack_install_upgrade_args(request):
    return request.param


class TestCurseForgeClient:
    def test_install_modpack(self, curseforge_client, pack_install_upgrade_args):
        """
        Tests that install_modpack calls _setup_modpack with the correct arguments.
        """
        project_id, file_id, instance_name = pack_install_upgrade_args
        curseforge_client._setup_modpack = mock.MagicMock(spec=curseforge_client._setup_modpack)

        curseforge_client.install_modpack(project_id, file_id, instance_name)

        curseforge_client._setup_modpack.assert_called_with("install", project_id, file_id, instance_name)

    @pytest.mark.parametrize("project_id", [1000, 5000])
    def test_project(self, curseforge_client, project_id):
        """
        Test that project returns a CurseForgeProject with the correct ID.
        """
        project = curseforge_client.project(project_id)

        assert isinstance(project, mccdl.CurseForgeProject)
        assert project.project_id == project_id

    def test_upgrade_modpack(self, curseforge_client, pack_install_upgrade_args):
        """
        Tests that upgrade_modpack calls _setup_modpack with the correct arguments.
        """
        project_id, file_id, instance_name = pack_install_upgrade_args
        curseforge_client._setup_modpack = mock.MagicMock(spec=curseforge_client._setup_modpack)

        curseforge_client.upgrade_modpack(project_id, file_id, instance_name)

        curseforge_client._setup_modpack.assert_called_with("upgrade", project_id, file_id, instance_name)

    def test_setup_modpack(self, curseforge_client, project, modpack, modpack_file_list,
                           multimc_instance_manager, multimc_instance, pack_install_upgrade_args):
        """
        Tests that _setup_modpack behaves correctly.
        """
        project_id, file_id, instance_name = pack_install_upgrade_args

        curseforge_client.project = mock.MagicMock(return_value=project)

        with mock.patch("mccdl.CurseForgeModPack", mock.MagicMock(return_value=modpack)):
            curseforge_client._setup_modpack("install", project_id, file_id, instance_name)

        multimc_instance.create.assert_called_with(modpack.minecraft_version,
                                                   modpack.forge_version, project.download_icon())
        for f in modpack_file_list:
            project.download_file.assert_any_call(
                f.file_id, multimc_instance.mods_directory, game_version=modpack.minecraft_version
            )

    @pytest.mark.parametrize("url_parts, expected_url", [
        (["projects"], "http://minecraft.curseforge.com/projects"),
        (["projects", "10000"], "http://minecraft.curseforge.com/projects/10000"),
        (["projects", "10000", "files", "1"], "http://minecraft.curseforge.com/projects/10000/files/1"),
    ])
    def test_url_for(self, curseforge_client, url_parts, expected_url):
        """
        Tests that url_for correctly constructs URLs.
        """
        actual_url = curseforge_client.url_for(*url_parts)

        assert actual_url == expected_url

    @pytest.mark.parametrize("url, expected_project_id, expected_file_id", [
        ("https://mods.curse.com/modpacks/minecraft/261783-ftb-beyond", "261783", "latest"),
        ("https://minecraft.curseforge.com/projects/invasion/files/2402833/download", "invasion", "2402833")
    ])
    def test_url_to_project_and_file(self, curseforge_client, url, expected_project_id, expected_file_id):
        """
        Tests that a Curse URL can correctly be decomposed into a project ID and file ID.
        """

        project_id, file_id = curseforge_client.url_to_project_and_file(url)

        assert project_id == expected_project_id
        assert file_id == expected_file_id

    def test_url_to_project_and_file_invalid_url(self, curseforge_client):
        """
        Tests that url_to_project_and_file raises an exception when given an invalid URL.
        """
        with pytest.raises(mccdl.InvalidCurseModpackUrlError):
            curseforge_client.url_to_project_and_file("https://www.google.com")
