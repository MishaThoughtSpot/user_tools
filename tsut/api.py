import json
import logging
import requests
import sys
import time
import tempfile

from .model import User, Group, UsersAndGroups

logger = logging.getLogger()
logger.setLevel(logging.DEBUG)

"""
Copyright 2018 ThoughtSpot
Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated
documentation files (the "Software"), to deal in the Software without restriction, including without limitation the
rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to
permit persons to whom the Software is furnished to do so, subject to the following conditions:
The above copyright notice and this permission notice shall be included in all copies or substantial portions
of the Software.
THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED
TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT,
TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
"""

# -------------------------------------------------------------------------------------------------------------------

"""Classes to work with the TS public user and list APIs"""

# Helper functions. ----------------------------------------------------------------------


def eprint(*args, **kwargs):
    """
    Prints to standard error similar to regular print.
    :param args:  Positional arguments.
    :param kwargs:  Keyword arguments.
    """
    print(*args, file=sys.stderr, **kwargs)


class UGJsonReader:
    """
    Reads a user / group structure from JSON and returns a UserGroup object.
    """

    def read_from_file(self, filename):
        """
        Reads the JSON data from a file.
        :param filename: Name of the file to read.
        :type filename: str
        :return: A UsersAndGroups container based on the JSON.
        :rtype: UsersAndGroups
        """
        with open(filename, "r") as json_file:
            json_list = json.load(json_file)
            return self.parse_json(json_list)

    def read_from_string(self, json_string):
        """
        Reads the users and groups from a JSON string.
        :param json_string: String containing the JSON.
        :type json_string: str
        :return: A UsersAndGroups container based on the JSON.
        :rtype: UsersAndGroups
        """
        json_list = json.loads(json_string)
        return self.parse_json(json_list)

    @staticmethod
    def parse_json(json_list):
        """
        Parses a JSON list and creates a UserAndGroup object.
        :param json_list: List of JSON objects that represent users and groups.
        :returns: A user and group container with the users and groups.
        :rtype: UsersAndGroups
        """
        auag = UsersAndGroups()
        for value in json_list:
            if str(value["principalTypeEnum"]).endswith("_USER"):
                user = User(
                    name=value.get("name", None),
                    display_name=value.get("displayName", None),
                    mail=value.get("mail", None),
                    group_names=value.get("groupNames", None),
                    visibility=value.get("visibility", None),
                    created=value.get("created", None),
                    user_id=value.get("id", None)
                )
                # TODO remove after testing.
                if auag.has_user(user.name):
                    logging.warning(f"Duplicate user {user.name} already exists.")
                else:
                    auag.add_user(user)
            else:
                group = Group(
                    name=value.get("name", None),
                    display_name=value.get("displayName", None),
                    description=value.get("description", None),
                    group_names=value.get("groupNames", None),
                    visibility=value.get("visibility", None),
                )
                auag.add_group(group)
        return auag


def api_call(f):
    """
    Makes sure to try to call login if not already logged in.  This only works for classes that extend BaseApiInterface.
    :param f: Function to decorate.
    :return: A new callable method that will try to login first.
    """

    def wrap(self, *args, **kwargs):
        """
        Verifies that the user is logged in and then makes the call.  Assumes something will be returned.
        :param self:  Instance calling a method.
        :param args:  Place arguments.
        :param kwargs: Key word arguments.
        :return: Whatever the wrapped method returns.
        """
        if not self.is_authenticated():
            self.login()
        return f(self, *args, **kwargs)

    return wrap


class BaseApiInterface:
    """
    Provides basic support for calling the ThoughtSpot APIs, particularly for logging in.
    """
    SERVER_URL = "{tsurl}/callosum/v1"

    def __init__(self, tsurl, username, password, disable_ssl=False):
        """
        Creates a new sync object and logs into ThoughtSpot
        :param tsurl: Root ThoughtSpot URL, e.g. http://some-company.com/
        :type tsurl: str
        :param username: Name of the admin login to use.
        :type username: str
        :param password: Password for admin login.
        :type password: str
        :param disable_ssl: If true, then disable SSL for calls.
        password for all users.  This can be significantly faster than individual passwords.
        """
        self.tsurl = tsurl
        self.username = username
        self.password = password
        self.cookies = None
        self.session = requests.Session()
        if disable_ssl:
            self.session.verify = False
        self.session.headers = {"X-Requested-By": "ThoughtSpot"}

    def login(self):
        """
        Log into the ThoughtSpot server.
        """
        url = self.format_url(SyncUserAndGroups.LOGIN_URL)
        response = self.session.post(
            url, data={"username": self.username, "password": self.password}
        )

        if response.status_code == 204:
            self.cookies = response.cookies
            logging.info(f"Successfully logged in as {self.username}")
        else:
            logging.error(f"Failed to log in as {self.username}")
            raise requests.ConnectionError(
                f"Error logging in to TS ({response.status_code})",
                response.text,
            )

    def is_authenticated(self):
        """
        Returns true if the session is authenticated
        :return: True if the session is authenticated.
        :rtype: bool
        """
        return self.cookies is not None

    def format_url(self, url):
        """
        Returns a URL that has the correct server.
        :param url: The URL template to add the server to.
        :type url: str
        :return: A URL that has the correct server info.
        :rtype: str
        """
        url = BaseApiInterface.SERVER_URL + url
        return url.format(tsurl=self.tsurl)


class SyncUserAndGroups(BaseApiInterface):
    """
    Synchronized with ThoughtSpot and also gets users and groups from ThoughtSpot.
    """

    LOGIN_URL = "/tspublic/v1/session/login"
    GET_ALL_URL = "/tspublic/v1/user/list"
    SYNC_ALL_URL = "/tspublic/v1/user/sync"
    UPDATE_PASSWORD_URL = "/tspublic/v1/user/updatepassword"
    DELETE_USERS_URL = "/session/user/deleteusers"
    DELETE_GROUPS_URL = "/session/group/deletegroups"
    USER_METADATA_URL = "/tspublic/v1/metadata/listobjectheaders?type=USER&batchsize=-1"
    GROUP_METADATA_URL = "/tspublic/v1/metadata/listobjectheaders?type=USER_GROUP&batchsize=-1"

    def __init__(
        self,
        tsurl,
        username,
        password,
        disable_ssl=False,
        global_password=False,
    ):
        """
        Creates a new sync object and logs into ThoughtSpot
        :param tsurl: Root ThoughtSpot URL, e.g. http://some-company.com/
        :param username: Name of the admin login to use.
        :param password: Password for admin login.
        :param disable_ssl: If true, then disable SSL for calls.
        :param global_password: If provided, will be passed to the sync call.  This is used to have a single
        password for all users.  This can be significantly faster than individual passwords.
        """
        super(SyncUserAndGroups, self).__init__(
            tsurl=tsurl,
            username=username,
            password=password,
            disable_ssl=disable_ssl,
        )
        self.global_password = global_password

    @api_call
    def get_all_users_and_groups(self):
        """
        Returns all users and groups from the server.
        :return: All users and groups from the server.
        :rtype: UsersAndGroups
        """

        url = self.format_url(SyncUserAndGroups.GET_ALL_URL)
        response = self.session.get(url, cookies=self.cookies)
        if response.status_code == 200:
            logging.info("Successfully got users and groups.")
            logging.debug(response.text)
            json_list = json.loads(response.text)
            reader = UGJsonReader()
            auag = reader.parse_json(json_list=json_list)
            return auag

        else:
            logging.error("Failed to get users and groups.")
            raise requests.ConnectionError(
                f"Error getting users and groups ({response.status_code})",
                response.text,
            )

    @api_call
    def get_user_metadata(self):
        """
        Returns a list of User objects based on the metadata.
        :return: A list of user objects.
        :rtype: list of User
        """
        url = self.format_url(SyncUserAndGroups.USER_METADATA_URL)
        response = self.session.get(url, cookies=self.cookies)
        users = []
        if response.status_code == 200:
            logging.info("Successfully got user metadata.")
            json_list = json.loads(response.text)
            logging.debug("metadata for users:  %s" % response.text)
            for value in json_list:
                user = User(
                    name=value.get("name", None),
                    display_name=value.get("displayName", None),
                    mail=value.get("mail", None),
                    group_names=value.get("groupNames", None),
                    visibility=value.get("visibility", None),
                    created=value.get("created", None),
                    user_id=value.get("id", None)
                )
                users.append(user)
            return users

        else:
            logging.error("Failed to get user metadata.")
            raise requests.ConnectionError(
                "Error getting user metadata (%d)" % response.status_code,
                response.text,
                )

    def sync_users_and_groups(self, users_and_groups, apply_changes=True,
                              remove_deleted=False, batch_size=-1, merge_groups=False):
        """
        Syncs users and groups.
        :param users_and_groups: List of users and groups to sync.
        :type users_and_groups: UsersAndGroups
        :param apply_changes: If true, changes will be applied.  If not, then it just says what will happen.
        :type apply_changes: bool
        :param remove_deleted: Flag to removed deleted users.  If true, delete.  Cannot be used with batch_size.
        :type remove_deleted: bool
        :param batch_size: The size of users to batch into a load.  Note that this cannot be combined with
        remove_deleted.
        :type batch_size: int
        :param merge_groups: Flag to indicate if groups should be merged.  True means add to old groups.
        :type merge_groups: bool
        """

        if not apply_changes:
            print("Testing sync.  Changes will not be applied.  Use --apply_changes flag to apply.")

        if remove_deleted and batch_size > 0:
            raise Exception("Cannot have remove_deleted True and batch_size > 0")

        if merge_groups:
            existing_ugs = self.get_all_users_and_groups()
            SyncUserAndGroups.__merge_groups_into_new(existing_ugs, users_and_groups)

        # Sync in batches
        if batch_size > 0:
            all_users = users_and_groups.get_users()
            while len(all_users) > 0:
                # get a batch of users to sync.
                user_batch = all_users[:batch_size]
                del all_users[:batch_size]

                ug_batch = UsersAndGroups()
                for user in user_batch:
                    ug_batch.add_user(users_and_groups.get_user(user.name))
                    for group_name in user.groupNames:  # Add the user's groups as well.
                        ug_batch.add_group(users_and_groups.get_group(group_name=group_name),
                                           duplicate=UsersAndGroups.IGNORE_ON_DUPLICATE)

                self._sync_users_and_groups(users_and_groups=users_and_groups,
                                            apply_changes=apply_changes, remove_deleted=remove_deleted)

        # Sync all users and groups.
        else:
            self._sync_users_and_groups(users_and_groups=users_and_groups,
                                        apply_changes=apply_changes, remove_deleted=remove_deleted)

    @staticmethod
    def __merge_groups_into_new(original_ugs, new_ugs):
        """
        Merges the original groups for the users in the new users and groups.  Useful when updating and not replacing
        users.
        :param original_ugs: The original users and groups, possibly from ThoughtSpot.
        :type original_ugs: UsersAndGroups
        :param new_ugs: The new users and groups that will be synced.
        :type new_ugs: UsersAndGroups
        :return: Nothing.  New users and groups list is updated.
        :rtype: None
        """
        for new_user in new_ugs.get_users():
            original_user = original_ugs.get_user(new_user.name)
            if original_user:
                new_user.groupNames.extend(original_user.groupNames)

    @api_call
    def _sync_users_and_groups(self, users_and_groups, apply_changes=True, remove_deleted=False):
        """
        Syncs users and groups.
        :param users_and_groups: List of users and groups to sync.
        :type users_and_groups: UsersAndGroups
        :param apply_changes: If true, changes will be applied.  If not, then it just says what will happen.
        :type apply_changes: bool
        :param remove_deleted: Flag to removed deleted users.  If true, delete.  Cannot be used with batch_size.
        :type remove_deleted: bool
        :returns: The response from the sync.
        """

        is_valid = users_and_groups.is_valid()
        if not is_valid[0]:
            # print("Invalid user and group structure.")
            raise Exception("Invalid users and groups")

        url = self.format_url(SyncUserAndGroups.SYNC_ALL_URL)

        logging.debug("calling %s" % url)
        json_str = users_and_groups.to_json()
        logging.info("%s" % json_str)
        json.loads(json_str)  # do a load to see if it breaks due to bad JSON.

        # Get the temp folder from the environment settings, so it will work cross platform.
        logging.debug("Using temp folder:"+tempfile.gettempdir())
        tmp_file = tempfile.gettempdir() + "/ug.json.%d" % time.time()

        with open(tmp_file, "w") as out:
            out.write(json_str)

        params = {
            "principals": (tmp_file, open(tmp_file, "rb"), "text/json"),
            "applyChanges": json.dumps(apply_changes),
            "removeDeleted": json.dumps(remove_deleted),
        }

        if self.global_password:
            params["password"] = self.global_password

        response = self.session.post(url, files=params, cookies=self.cookies)

        if response.status_code == 200:
            logging.info("Successfully synced users and groups.")
            logging.info(response.text.encode("utf-8"))
            return response

        else:
            logging.error("Failed synced users and groups.")
            logging.info(response.text.encode("utf-8"))
            with open("ts_users_and_groups.json", "w") as outfile:
                outfile.write(str(json_str.encode("utf-8")))
            raise requests.ConnectionError(
                "Error syncing users and groups (%d)" % response.status_code,
                response.text,
            )

    @api_call
    def delete_users(self, usernames):
        """
        Deletes a list of users based on their user name.
        :param usernames: List of the names of the users to delete.
        :type usernames: list of str
        """

        # for each username, get the guid and put in a list.  Log errors for users not found, but don't stop.
        logging.info("Deleting users %s." % usernames)
        url = self.format_url(SyncUserAndGroups.USER_METADATA_URL)
        response = self.session.get(url, cookies=self.cookies)
        users = {}
        if response.status_code == 200:
            logging.info("Successfully got user metadata.")
            logging.debug("response:  %s" % response.text)
            json_list = json.loads(response.text)
            for h in json_list:
                name = h["name"]
                user_id = h["id"]
                users[name] = user_id

            user_list = []
            for u in usernames:
                group_id = users.get(u, None)
                if not group_id:
                    logging.warning("User %s not found, not attempting to delete this user." % u)
                else:
                    user_list.append(group_id)

            if not user_list:
                logging.warning("No valid users to delete.")
                return

            logging.info("Deleting user IDs %s." % user_list)
            url = self.format_url(SyncUserAndGroups.DELETE_USERS_URL)
            params = {"ids": json.dumps(user_list)}
            response = self.session.post(
                url, data=params, cookies=self.cookies
            )

            if response.status_code != 204:
                logging.error("Failed to delete %s" % user_list)
                raise requests.ConnectionError(
                    "Error getting users and groups (%d)"
                    % response.status_code,
                    response.text,
                )

        else:
            logging.error("Failed to get users and groups.")
            raise requests.ConnectionError(
                "Error getting users and groups (%d)" % response.status_code,
                response.text,
            )

    def delete_user(self, username):
        """
        Deletes the user with the given username.
        :param username: The name of the user.
        :type username: str
        """
        self.delete_users([username])  # just call the list method.

    @api_call
    def delete_groups(self, groupnames):
        """
        Deletes a list of groups based on their group name.
        :param groupnames: List of the names of the groups to delete.
        :type groupnames: list of str
        """

        # for each groupname, get the guid and put in a list.  Log errors for groups not found, but don't stop.
        url = self.format_url(SyncUserAndGroups.GROUP_METADATA_URL)
        response = self.session.get(url, cookies=self.cookies)
        groups = {}
        if response.status_code == 200:
            logging.info("Successfully got group metadata.")
            json_list = json.loads(response.text)
            # for h in json_list["headers"]:
            for h in json_list:
                name = h["name"]
                group_id = h["id"]
                groups[name] = group_id

            group_list = []
            for u in groupnames:
                group_id = groups.get(u, None)
                if not group_id:
                    eprint(
                        "WARNING:  group %s not found, not attempting to delete this group."
                        % u
                    )
                else:
                    group_list.append(group_id)

            if not group_list:
                eprint("No valid groups to delete.")
                return

            url = self.format_url(SyncUserAndGroups.DELETE_GROUPS_URL)
            params = {"ids": json.dumps(group_list)}
            response = self.session.post(
                url, data=params, cookies=self.cookies
            )

            if response.status_code != 204:
                logging.error("Failed to delete %s" % group_list)
                raise requests.ConnectionError(
                    "Error getting groups and groups (%d)"
                    % response.status_code,
                    response.text,
                )

        else:
            logging.error("Failed to get users and groups.")
            raise requests.ConnectionError(
                "Error getting users and groups (%d)" % response.status_code,
                response.text,
            )

    def delete_group(self, groupname):
        """
        Deletes the group with the given groupname.
        :param groupname: The name of the group.
        :type groupname: str
        """
        self.delete_groups([groupname])  # just call the list method.

    @api_call
    def update_user_password(self, userid, currentpassword, password):
        """
        Updates the password for a user.
        :param userid: User id for the user to change the password for.
        :type userid: str
        :param currentpassword: Password for the logged in user with admin privileges.
        :type currentpassword: str
        :param password: New password for the user.
        :type password: str
        """

        url = self.format_url(SyncUserAndGroups.UPDATE_PASSWORD_URL)
        params = {
            "name": userid,
            "currentpassword": currentpassword,
            "password": password,
        }

        response = self.session.post(url, data=params, cookies=self.cookies)

        if response.status_code == 204:
            logging.info("Successfully updated password for %s." % userid)
        else:
            logging.error("Failed to update password for %s." % userid)
            raise requests.ConnectionError(
                "Error (%d) updating user password for %s:  %s"
                % (response.status_code, userid, response.text)
            )


class Privileges:
    """
    Contains the various privileges that groups can have.
    """
    IS_ADMINSTRATOR = "ADMINISTRATION"
    CAN_UPLOAD_DATA = "USERDATAUPLOADING"
    CAN_DOWNLOAD_DATA = "DATADOWNLOADING"
    CAN_SHARE_WITH_ALL = "SHAREWITHALL"
    CAN_MANAGE_DATA = "DATAMANAGEMENT"
    CAN_SCHEDULE_PINBOARDS = "JOBSCHEDULING"
    CAN_USE_SPOTIQ = "A3ANALYSIS"
    CAN_ADMINISTER_RLS = "BYPASSRLS"
    CAN_AUTHOR = "AUTHORING"
    CAN_MANAGE_SYSTEM = "SYSTEMMANAGEMENT"


class SetGroupPrivilegesAPI(BaseApiInterface):

    # Note that some of these URLs are not part of the public API and subject to change.
    METADATA_LIST_URL = "/tspublic/v1/metadata/listobjectheaders?type=USER_GROUP"
    METADATA_DETAIL_URL = "/metadata/detail/{guid}?type=USER_GROUP"

    ADD_PRIVILEGE_URL = "/tspublic/v1/group/addprivilege"
    REMOVE_PRIVILEGE_URL = "/tspublic/v1/group/removeprivilege"

    def __init__(self, tsurl, username, password, disable_ssl=False):
        """
        Creates a new sync object and logs into ThoughtSpot
        :param tsurl: Root ThoughtSpot URL, e.g. http://some-company.com/
        :param username: Name of the admin login to use.
        :param password: Password for admin login.
        :param disable_ssl: If true, then disable SSL for calls.
        """
        super(SetGroupPrivilegesAPI, self).__init__(
            tsurl=tsurl,
            username=username,
            password=password,
            disable_ssl=disable_ssl,
        )

    @api_call
    def get_privileges_for_group(self, group_name):
        """
        Gets the current privileges for a given group.
        :param group_name:  Name of the group to get privileges for.
        :returns: A list of privileges.
        :rtype: list of str
        """
        url = self.format_url(
            SetGroupPrivilegesAPI.METADATA_LIST_URL
        ) + "&pattern=" + group_name
        response = self.session.get(url, cookies=self.cookies)
        if response.status_code == 200:  # success
            results = json.loads(response.text)
            try:
                group_id = results[0][
                    "id"
                ]  # should always be present, but might want to add try / catch.
                detail_url = SetGroupPrivilegesAPI.METADATA_DETAIL_URL.format(
                    guid=group_id
                )
                detail_url = self.format_url(detail_url)
                detail_response = self.session.get(
                    detail_url, cookies=self.cookies
                )
                if detail_response.status_code == 200:  # success
                    privileges = json.loads(detail_response.text)["privileges"]
                    return privileges

                else:
                    logging.error(
                        "Failed to get privileges for group %s" % group_name
                    )
                    raise requests.ConnectionError(
                        "Error (%d) setting privileges for group %s.  %s"
                        % (response.status_code, group_name, response.text)
                    )

            except Exception:
                logging.error("Error getting group details.")
                raise

        else:
            logging.error("Failed to get privileges for group %s" % group_name)
            raise requests.ConnectionError(
                "Error (%d) setting privileges for group %s.  %s"
                % (response.status_code, group_name, response.text)
            )

    @api_call
    def add_privilege(self, groups, privilege):
        """
        Adds a privilege to a list of groups.
        :param groups List of groups to add the privilege to.
        :type groups: list of str
        :param privilege: Privilege being set.
        :type privilege: str
        """

        url = self.format_url(SetGroupPrivilegesAPI.ADD_PRIVILEGE_URL)

        params = {"privilege": privilege, "groupNames": json.dumps(groups)}
        response = self.session.post(url, files=params, cookies=self.cookies)

        if response.status_code == 204:
            logging.info(
                "Successfully added privilege %s for groups %s."
                % (privilege, groups)
            )
        else:
            logging.error(
                "Failed to add privilege %s for groups %s."
                % (privilege, groups)
            )
            raise requests.ConnectionError(
                "Error (%d) adding privilege %s for groups %s.  %s"
                % (response.status_code, privilege, groups, response.text)
            )

    @api_call
    def remove_privilege(self, groups, privilege):
        """
        Removes a privilege to a list of groups.
        :param groups List of groups to add the privilege to.
        :type groups: list of str
        :param privilege: Privilege being removed.
        :type privilege: str
        """

        url = self.format_url(SetGroupPrivilegesAPI.REMOVE_PRIVILEGE_URL)

        params = {"privilege": privilege, "groupNames": json.dumps(groups)}
        response = self.session.post(url, files=params, cookies=self.cookies)

        if response.status_code == 204:
            logging.info(
                "Successfully removed privilege %s for groups %s."
                % (privilege, groups)
            )
        else:
            logging.error(
                "Failed to remove privilege %s for groups %s."
                % (privilege, groups)
            )
            raise requests.ConnectionError(
                "Error (%d) removing privilege %s for groups %s.  %s"
                % (response.status_code, privilege, groups, response.text)
            )


class TransferOwnershipApi(BaseApiInterface):

    TRANSFER_OWNERSHIP_URL = "/tspublic/v1/user/transfer/ownership"

    def __init__(self, tsurl, username, password, disable_ssl=False):
        """
        Creates a new sync object and logs into ThoughtSpot
        :param tsurl: Root ThoughtSpot URL, e.g. http://some-company.com/
        :param username: Name of the admin login to use.
        :param password: Password for admin login.
        :param disable_ssl: If true, then disable SSL for calls.
        """
        super(TransferOwnershipApi, self).__init__(
            tsurl=tsurl,
            username=username,
            password=password,
            disable_ssl=disable_ssl,
        )

    @api_call
    def transfer_ownership(self, from_username, to_username):
        """
        Transfer ownership of all objects from one user to another.
        :param from_username: User name for the user to change the ownership for.
        :type from_username: str
        :param to_username: User name for the user to change the ownership to.
        :type to_username: str
        """

        url = self.format_url(TransferOwnershipApi.TRANSFER_OWNERSHIP_URL)
        url = url + "?fromUserName=" + from_username + "&toUserName=" + to_username
        response = self.session.post(url, cookies=self.cookies)

        if response.status_code == 204:
            logging.info(
                "Successfully transferred ownership to %s." % to_username
            )
        else:
            logging.error("Failed to transfer ownership to %s." % to_username)
            raise requests.ConnectionError(
                f"Error ({response.status_code}) transferring  ownership to {to_username}:  {response.text}"
            )
