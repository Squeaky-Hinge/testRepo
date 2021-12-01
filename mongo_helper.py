import hashlib
import os

import pymongo
import logging

# standardized naming for all of the collections in the db
REPO_COL = "repo"
FILE_COL = "file"
FUNC_COL = "function"
USER_COL = "user"
COOKIE_COL = "cookie"


class MongoHelper:
    # Change <username> and <password> to username and password
    def __init__(self):
        try:
            self.client = pymongo.MongoClient(
                "mongodb+srv://admin:admin@cluster0.1xqz7.mongodb.net/shdb?retryWrites=true&w=majority"
            )
            self.db = self.client.get_default_database()
        except:
            logging.debug("Could not reach Mongo Atlas Server")

    # inserts a repo into the database, if one with the same branch owner and repo exists then it returns an error msg
    def write_repo(self, owner: str, repo: str, branch: str) -> dict:
        """Writes a repo document to the database

        :param owner: github owner to write to db
        :type owner: str

        :param repo: github repo to write to db
        :type repo: str

        :param branch: github branch to write to db
        :type branch: str

        :rtype: dict[str, str], response status and reason
        """
        # constructing query for finding a repo in the
        query = dict([("branch", branch), ("owner", owner), ("repo", repo)])

        # check if db query is None
        if self.db[REPO_COL].find_one(query) is None:
            repo_id = self.db[REPO_COL].insert_one(query)
            return {"status": "Success", "inserted id": f"{repo_id.inserted_id}"}
        else:
            return {
                "status": "Failed",
                "reason": f"repo for {owner} - {repo} - {branch} already exists",
            }

    # Retrieves a repo from the database if no database is found then it returns an error msg
    def get_repo(self, owner: str, repo: str, branch: str) -> dict:
        """Returns a repo document from the database

        :param owner: github owner to retrieve
        :type owner: str

        :param repo: github repo to retrieve
        :type repo: str

        :param branch: github branch to retrieve
        :type branch: str

        :rtype: dict[str, str], response status and reason
        or database document (dict)
        """
        query = dict([("branch", branch), ("owner", owner), ("repo", repo)])

        # query for first repo with matching branch owner and repo fields. There can only be one.
        doc = self.db[REPO_COL].find_one(query)
        if doc is None:
            return {
                "status": "Failed",
                "reason": f"no such repo for {owner} - {repo} - {branch} exists",
            }
        else:
            return doc

    # Returns the unique repo_id for the repo passed
    def get_repo_id(self, owner: str, repo: str, branch: str):
        """Returns a repo document from the database

        :param owner: github owner to retrieve
        :type owner: str

        :param repo: github repo to retrieve
        :type repo: str

        :param branch: github branch to retrieve
        :type branch: str

        :rtype: dict[str, str], response status and reason
        or dict[str, str] repo_id label and repo_id
        """
        query = dict([("branch", branch), ("owner", owner), ("repo", repo)])

        doc = self.db[REPO_COL].find_one(query)
        if doc is None:
            return {
                "repo_id": "Failed",
                "reason": f"no such repo for {owner} - {repo} - {branch} exists",
            }
        else:
            return dict([("repo_id", doc["_id"])])

    # Deletes a repo from the db and also deletes any files associated along with funcs associated with those files
    def delete_repo(self, owner: str, repo: str, branch: str) -> dict:
        """Deletes a repo document from the database

        :param owner: github owner to delete
        :type owner: str

        :param repo: github repo to delete
        :type repo: str

        :param branch: github branch to delete
        :type branch: str

        :rtype: dict[str, str], response status and reason
        """
        repo_id = self.get_repo_id(owner=owner, repo=repo, branch=branch)

        # if there is no repo id returns error message
        if repo_id["repo_id"] == "Failed":
            return {
                "status": "Failed",
                "reason": f"no such repo for " f"{owner} - {repo} - {branch} exists",
            }
        else:
            query = dict([("branch", branch), ("owner", owner), ("repo", repo)])
            files = self.db[FILE_COL].find(dict([("repo_id", repo_id["repo_id"])]))

            # check if the repo has associated files, if no the repo gets deleted from repo collection
            if files.count() == 0:
                self.db[REPO_COL].delete_one(query)
                return {
                    "status": "Success",
                    "reason": f"{owner} - {repo} - {branch} deleted",
                }
            # loop through files and call the delete file method
            else:
                for entry in files:
                    self.delete_file(
                        owner=owner, repo=repo, branch=branch, file_path=entry["path"]
                    )
                self.db[REPO_COL].delete_one(query)
                return {
                    "status": "Success",
                    "reason": f"{owner} - {repo} - {branch} deleted",
                }

    # Gets all files associated with a repo id
    def get_all_repo_files(self, owner: str, repo: str, branch: str):
        """retrieves all files for an owner-repo-branch

        :param owner: github owner for files
        :type owner: str

        :param repo: github repo for files
        :type repo: str

        :param branch: github branch for files
        :type branch: str

        :rtype: dict[str, str], response status and reason or
        dict[str, list[dict[str, str]] all files in for an owner
        branch repo
        """
        repo_id = self.get_repo_id(owner=owner, repo=repo, branch=branch)

        if repo_id["repo_id"] == "Failed":
            return {
                "status": "Failed",
                "reason": f"no such repo for " f"{owner} - {repo} - {branch} exists",
            }
        else:
            # query the file collection for all files with repo id
            docs = self.db[FILE_COL].find(dict([("repo_id", repo_id["repo_id"])]))
            file_list = []
            # iterate through the file documents and return them in a dict
            for file in docs:
                file_list.append(file)
            return dict([("files", file_list)])

    # Writes a file analysis to the db if there is already a file with lower number of commits then it deletes it and
    # writes a new one.
    def write_file(self, file_data: dict, owner: str, repo: str, branch: str):
        """Writes a file to the db and uses write_function to
        write all the file functions to the db

        :param file_data: file information to store
        :type file_data: dict

        :param owner: github owner for file
        :type owner: str

        :param repo: github repo for file
        :type repo: str

        :param branch: github branch for file
        :type branch: str

        :rtype: dict[str, str], response status and reason
        """
        repo_id = self.get_repo_id(owner=owner, repo=repo, branch=branch)

        query = dict([("repo_id", repo_id["repo_id"]), ("path", file_data["path"])])

        docs = self.db[FILE_COL].find_one(query)

        # if the file that we query for is not found it is inserted
        if docs is None:
            insertion = dict(
                [
                    ("file_lock", False),
                    ("repo_id", repo_id["repo_id"]),
                    ("path", file_data["path"]),
                    ("last_commit", file_data["last_commit"]),
                    ("commits", file_data["commits"]),
                    ("line_history", file_data["line_history"]),
                ]
            )

            self.db[FILE_COL].insert_one(insertion)

            # write all the file functions to the db function collection
            self.write_functions(
                file_data=file_data,
                owner=owner,
                repo=repo,
                branch=branch,
                file_path=file_data["path"],
            )

            return {
                "status": "Success",
                "reason": f"{file_data['path']} has been inserted",
            }

        # if the file is found, check if it has a lower num commits than the file passed from analyze
        else:
            if docs["commits"] < file_data["commits"]:

                # delete the file which returns all the user defined fields to pass back into write_functions
                user_score = self.delete_file(
                    owner=owner, repo=repo, branch=branch, file_path=file_data["path"]
                )
                insertion = dict(
                    [
                        ("repo_id", repo_id["repo_id"]),
                        ("path", file_data["path"]),
                        ("last_commit", file_data["last_commit"]),
                        ("commits", file_data["commits"]),
                        ("line_history", file_data["line_history"]),
                    ]
                )

                self.db[FILE_COL].insert_one(insertion)

                # write all the functions to the db with the old user defined fields
                self.write_functions(
                    file_data=file_data,
                    owner=owner,
                    repo=repo,
                    branch=branch,
                    file_path=file_data["path"],
                    user_score=user_score,
                )

                return {
                    "status": "Success",
                    "reason": f"{file_data['path']} has been updated",
                }
            # if the number of commits is the same then we do nothing
            else:
                return {
                    "status": "Failed",
                    "reason": f"{file_data['path']} is up to date",
                }

    # Returns an analyzed file document from the database
    def get_file(self, owner: str, repo: str, branch: str, file_path: str) -> dict:
        """returns a file document from the db

        :param owner: github owner for file
        :type owner: str

        :param repo: github repo for file
        :type repo: str

        :param branch: github branch for file
        :type branch: str

        :param file_path: root path to the file in github repo
        :type file_path: str

        :rtype: dict[str, str], response status and reason or
        file document from the db
        """
        repo_id = self.get_repo_id(owner=owner, repo=repo, branch=branch)
        query = dict([("repo_id", repo_id["repo_id"]), ("path", file_path)])

        doc = self.db[FILE_COL].find_one(query)

        if doc is None:
            return {
                "status": "Failed",
                "reason": f"no such file for {owner} - {repo} - {branch} - {file_path} exists",
            }
        else:
            return doc

    def get_lock_status(self, owner: str, repo: str, branch: str, file_path: str):
        """returns the lock field from a specified file in the db

        :param owner: github owner for file
        :type owner: str

        :param repo: github repo for file
        :type repo: str

        :param branch: github branch for file
        :type branch: str

        :param file_path: root path to the file in github repo
        :type file_path: str

        :rtype: dict[str, str], response status and reason or
        dict[str, bool], lock_status and T or F
        """
        file_id = self.get_file_id(
            owner=owner, repo=repo, branch=branch, file_path=file_path
        )

        if file_id["file_id"] == "Failed":
            return {
                "status": "Failed",
                "reason": f"no such file "
                f"{owner} - {repo} - {branch} - {file_path} exists",
            }
        else:
            doc = self.db[FILE_COL].find_one(file_id["file_id"])
            return dict([("lock_status", doc["file_lock"])])

    # Updates the file_lock value in for a file
    def update_lock(
        self, owner: str, repo: str, branch: str, file_path: str, lock: bool
    ):
        """updates the lock field in a file document in the db

        :param owner: github owner for file
        :type owner: str

        :param repo: github repo for file
        :type repo: str

        :param branch: github branch for file
        :type branch: str

        :param file_path: root path to the file in github repo
        :type file_path: str

        :param lock: lock status in the db
        :type lock: bool

        :rtype: dict[str, str], response status and reason or
        dict[str, bool], lock label and T or F
        """
        file_id = self.get_file_id(
            owner=owner, repo=repo, branch=branch, file_path=file_path
        )

        # if no file exists return error
        if file_id["file_id"] == "Failed":
            return {
                "status": "Failed",
                "reason": f"no such file "
                f"{owner} - {repo} - {branch} - {file_path} exists",
            }
        # update the file lock in the file document and then return what it was changed to
        else:
            query = dict([("_id", file_id)])
            self.db[FILE_COL].update(query, {"$set": dict([("file_lock", lock)])})
            return dict([("lock_status", lock)])

    # returns the file id if one exists for the given path owner, repo and branch or returns none if one is not found
    def get_file_id(self, owner: str, repo: str, branch: str, file_path: str) -> dict:
        """returns the file id

        :param owner: github owner for file
        :type owner: str

        :param repo: github repo for file
        :type repo: str

        :param branch: github branch for file
        :type branch: str

        :param file_path: root path to the file in github repo
        :type file_path: str

        :rtype: dict[str, str], response status and reason or
        file_id label and file_id
        """
        repo_id = self.get_repo_id(owner=owner, repo=repo, branch=branch)

        query = dict([("repo_id", repo_id["repo_id"]), ("path", file_path)])

        doc = self.db[FILE_COL].find_one(query)

        if doc is None:
            return {
                "file_id": "Failed",
                "reason": f"no such repo for {owner} - {repo} - {branch} - {file_path} exists",
            }
        else:
            return dict([("file_id", doc["_id"])])

    # deletes a file from the db
    def delete_file(self, owner: str, repo: str, branch: str, file_path: str) -> dict:
        """deletes a file from the db *if questioning why this
        returns dict[str, str] or int please see 244-271

        :param owner: github owner for file
        :type owner: str

        :param repo: github repo for file
        :type repo: str

        :param branch: github branch for file
        :type branch: str

        :param file_path: root path to the file in github repo
        :type file_path: str

        :rtype: dict[str, str], response status and message or
        user score to limit read and writes in the db
        """
        file_id = self.get_file_id(
            owner=owner, repo=repo, branch=branch, file_path=file_path
        )
        if file_id["file_id"] == "Failed":
            return {
                "status": "Failed",
                "reason": f"no such file "
                f"{owner} - {repo} - {branch} - {file_path} exists",
            }
        # if the file does exist we delete all the methods because they will be linked to a diff file_id
        else:
            user_score = self.delete_functions(
                owner=owner, repo=repo, branch=branch, file_path=file_path
            )
            deleted = self.db[FILE_COL].delete_one(dict([("_id", file_id["file_id"])]))

            # this shouldn't happen but if it does we know there is an error
            if deleted.deleted_count == 0:
                return {"status": "Failed", "reason": f"no file named {file_path}"}
            else:
                return user_score

    # Writes functions of a file to the db. this will be utilized via the write_file method
    def write_functions(
        self,
        file_data: dict,
        owner: str,
        repo: str,
        branch: str,
        file_path: str,
        user_score: dict = None,
    ) -> dict:
        """Writes a function doc to the db

        :param file_data: file and function data to write
        :type file_data: dict

        :param owner: github owner for file
        :type owner: str

        :param repo: github repo for file
        :type repo: str

        :param branch: github branch for file
        :type branch: str

        :param file_path: root path to the file in github repo
        :type file_path: str

        :param user_score: input score from user
        :type user_score: int or none

        :rtype: dict[str, str], response status and reason
        """
        file_id = self.get_file_id(
            owner=owner, repo=repo, branch=branch, file_path=file_path
        )
        if file_id["file_id"] == "Failed":
            return {
                "status": "Failed",
                "reason": f"no such file "
                f"{owner} - {repo} - {branch} - {file_path} exists",
            }
        else:

            # if there aren't any user_score obj passed we write the functions of the file with automatic 0 for
            # user_score
            if user_score is None:
                inserted = []
                for func in file_data["functions"]:
                    insertion = dict(
                        [("file_id", file_id["file_id"]), ("user_score", 0)]
                    )
                    insertion.update(func)
                    function_id = self.db[FUNC_COL].insert_one(insertion)
                    inserted.append(function_id.inserted_id)
                return dict([("files_inserted", inserted)])

            # if user_score is passed we write the functions with the previous user_scores
            else:
                inserted = []
                for func in file_data["functions"]:
                    insertion = dict(
                        [
                            ("file_id", file_id["file_id"]),
                            ("user_score", user_score[func["name"]]),
                        ]
                    )
                    insertion.update(func)
                    function_id = self.db[FUNC_COL].insert_one(insertion)
                    inserted.append(function_id.inserted_id)
                return dict([("files_inserted", inserted)])

    # Returns all the functions in a file analysis as a dict
    def get_functions(self, owner: str, repo: str, branch: str, file_path: str) -> dict:
        """returns all function docs for a file doc

        :param owner: github owner for file
        :type owner: str

        :param repo: github repo for file
        :type repo: str

        :param branch: github branch for file
        :type branch: str

        :param file_path: root path to the file in github repo
        :type file_path: str

        :rtype: dict[str, str], response status and reason or
        functions label and list of function docs
        """
        file_id = self.get_file_id(
            owner=owner, repo=repo, branch=branch, file_path=file_path
        )

        docs = self.db[FUNC_COL].find(dict([("file_id", file_id["file_id"])]))

        if docs is None:
            return {
                "status": "Failed",
                "reason": f"no such functions for "
                f"{owner} - {repo} - {branch} - {file_path} exist",
            }
        else:
            funcs = []
            for entry in docs:
                funcs.append(entry)
            return dict([("functions", funcs)])

    # gets a single function from the db
    def get_function(
        self, owner: str, repo: str, branch: str, file_path: str, func_name: str
    ) -> dict:
        """returns a function doc

        :param owner: github owner for file
        :type owner: str

        :param repo: github repo for file
        :type repo: str

        :param branch: github branch for file
        :type branch: str

        :param file_path: root path to the file in github repo
        :type file_path: str

        :param func_name: name of the function
        :type func_name: str

        :rtype: dict[str, str], response status and reason or
        function doc
        """
        file_id = self.get_file_id(
            owner=owner, repo=repo, branch=branch, file_path=file_path
        )

        doc = self.db[FUNC_COL].find_one(
            dict([("file_id", file_id["file_id"]), ("name", func_name)])
        )

        if doc is None:
            return {
                "status": "Failed",
                "reason": f"no such functions for "
                f"{owner} - {repo} - {branch} - {file_path} exist",
            }
        else:
            return doc

    # Deletes all functions associated with a file
    def delete_functions(
        self, owner: str, repo: str, branch: str, file_path: str
    ) -> dict:
        """Deletes all functions associated with a file doc

        :param owner: github owner for file
        :type owner: str

        :param repo: github repo for file
        :type repo: str

        :param branch: github branch for file
        :type branch: str

        :param file_path: root path to the file in github repo
        :type file_path: str

        :rtype: dict[str, str], response status and reason or
        user score to limit read and writes in the db
        """
        file_id = self.get_file_id(
            owner=owner, repo=repo, branch=branch, file_path=file_path
        )
        if file_id["file_id"] == "Failed":
            return {
                "status": "Failed",
                "reason": f"no such file "
                f"{owner} - {repo} - {branch} - {file_path} exists",
            }

        # search by file id to get user fields and then return them as a dict organized by name
        else:
            query = dict([("file_id", file_id["file_id"])])
            get_user_scores = self.db[FUNC_COL].find(query)
            user_score = dict()
            for func in get_user_scores:
                user_score.update(dict([(func["name"], func["user_score"])]))
            deleted = self.db[FUNC_COL].delete_many(query)
            if deleted.deleted_count == 0:
                return {
                    "status": "Failed",
                    "reason": f"no functions listed for file {file_path}",
                }
            else:
                return user_score

    # Updates a file if you pass the file id and what you would like to change. This may be needed later
    def update_file(self, query: dict, fix: dict) -> None:
        """updates a file doc in the db(mainly for testing)

        :param query: query params to look for a file doc
        :type query: dict

        :param fix: updated fields and values
        :type fix: dict

        :rtype: None,
        """
        self.db[FILE_COL].update(query, {"$set": fix})

    # updates the user field for specific functions
    def update_user_score(
        self,
        owner: str,
        repo: str,
        branch: str,
        file_path: str,
        func_name: str,
        user_val: int,
    ):
        """Updates the user_score value in a function doc

        :param owner: github owner for file
        :type owner: str

        :param repo: github repo for file
        :type repo: str

        :param branch: github branch for file
        :type branch: str

        :param file_path: root path to the file in github repo
        :type file_path: str

        :param func_name: name of function
        :type func_name: str

        :param user_val: user input value
        :type user_val: int

        :rtype: dict[str, str], response status and reason
        """
        doc = self.get_function(
            owner=owner,
            repo=repo,
            branch=branch,
            file_path=file_path,
            func_name=func_name,
        )
        if doc is None:
            return {
                "status": "Failed",
                "reason": f"no functions listed for file {file_path}",
            }
        else:
            query = dict([("file_id", doc["file_id"]), ("name", func_name)])
            self.db[FUNC_COL].update(query, {"$set": dict([("user_score", user_val)])})
            return {"status": "Success", "reason": f"successfully updated {func_name}"}

    # Creates a new user in the db with a unique username
    def create_user(
        self,
        first_name: str,
        last_name: str,
        user_name: str,
        password: str,
        email: str,
        dev_access: [],
    ) -> dict:
        """Creates a new user doc in the db

        :param first_name: first name of user
        :type first_name: str

        :param last_name: last name of user
        :type last_name: str

        :param user_name: unique username of user
        :type user_name: str

        :param password: password of the user
        :type password: str

        :param email: email of user
        :type email: str

        :param dev_access: development access of user
        :type dev_access: list

        :rtype: dict[str, str], response status and reason
        """
        doc = self.db[USER_COL].find(dict([("user_name", user_name)]))
        if doc.count() == 0:
            insertion = dict(
                [
                    ("dev_access", dev_access),
                    ("first_name", first_name),
                    ("last_name", last_name),
                    ("email", email),
                    ("user_name", user_name),
                ]
            )

            # used update here because secure_password returns a dict
            insertion.update(self.secure_password(password))
            result = self.db[USER_COL].insert_one(insertion)

            return {
                "status": "Success",
                "reason": f"user with id: {result.inserted_id} has been created",
            }
        else:
            return {
                "status": "Failed",
                "reason": f"There is already a user associated with user name: {user_name}",
            }

    # Salts and hashes the password provided and returns a dict with the salt and hash so the db can store this.
    @staticmethod
    def secure_password(password: str) -> dict:
        """hashes a password in 256

        :param password: password to be hashed
        :type password: str

        :rtype: dict[str, str], returns the salt and the hash
        of the password
        """

        salt = os.urandom(32)
        secured_password = hashlib.pbkdf2_hmac(
            hash_name="sha256",
            password=password.encode("utf-8"),
            salt=salt,
            iterations=1000,
        )
        # return the salt and has to store in the users document in the database
        return dict([("salt", salt), ("secured_password", secured_password)])

    # Returns a user doc by passing username
    def get_user(self, user_name: str) -> dict:
        """retrieves a user doc from the db

        :param user_name: unique username of user
        :type user_name: str

        :rtype: dict[str, str], response status and reason
        of user doc
        """

        doc = self.db[USER_COL].find_one(dict([("user_name", user_name)]))
        if doc is None:
            return {
                "status": "Failed",
                "reason": f"There is no user associated with user name: {user_name}",
            }
        else:
            return doc

    # Verifies a user login via username and password passed
    def verify_user_login(self, password: str, username: str) -> bool:
        """hashes a password and verifies it to the
        user password in the user doc

        :param password: password to be hashed
        :type password: str

        :param username: username of user
        :type username: str

        :rtype: bool, returns if hashed password matches
        the one stored in db
        """
        doc = self.db[USER_COL].find_one(dict([("user_name", username)]))
        secured_password = hashlib.pbkdf2_hmac(
            hash_name="sha256",
            password=password.encode("utf-8"),
            salt=doc["salt"],
            iterations=1000,
        )

        if secured_password == doc["secured_password"]:
            return True
        else:
            return False

    # deletes a user from the db by username
    def delete_user(self, user_name: str) -> dict:
        """Deletes a user doc in the db

        :param user_name: unique username of user
        :type user_name: str

        :rtype: dict[str, str], response status and reason
        """
        doc = self.db[USER_COL].find_one(dict([("user_name", user_name)]))
        if doc is None:
            return {
                "status": "Failed",
                "reason": f"There is no user associated with user name: {user_name}",
            }
        else:
            self.db[USER_COL].delete_one(dict([("user_name", user_name)]))
            return {"status": "Success", "reason": f"User {user_name} has been deleted"}

    # Updates user by passing a dict of fields or field to update on the file document
    def update_user(self, user_name: str, fix: dict) -> dict:
        """Updates a user doc in the db

        :param user_name: unique username of user
        :type user_name: str

        :param fix: fields to fix
        :type fix: dict

        :rtype: dict[str, str], response status and reason
        """
        query = dict([("user_name", user_name)])
        doc = self.db[USER_COL].find_one(query)
        if doc is None:
            return {
                "status": "Failed",
                "reason": f"There is no user associated with user name: {user_name}",
            }
        else:
            self.db[USER_COL_COL].update(query, {"$set": fix})
            return {"status": "Success", "reason": f"User {user_name} has been updated"}

    # Writes a cookie to the db after checking for a username provided
    def write_cookie(self, user_name: str, cookie: str) -> dict:
        """Writes a cookie doc to the db

        :param user_name: unique username of user
        :type user_name: str

        :param cookie: unique cookie value
        :type cookie: str

        :rtype: dict[str, str], response status and reason
        """
        doc = self.db[USER_COL].find_one(dict([("user_name", user_name)]))
        # Check if a user with username exists
        if doc is None:
            return {
                "status": "Failed",
                "reason": f"There is no user associated with user name: {user_name}",
            }
        # If they do, write a cookie
        else:
            ret = self.db[COOKIE_COL].insert_one(
                dict([("user_name", user_name), ("cookie", cookie)])
            )
            if ret.inserted_id is None:
                return {
                    "status": "Failed",
                    "reason": f"There is no user associated with user name: {user_name}",
                }
            else:
                return {
                    "status": "Success",
                    "reason": f"Cookie with insertion ID {ret.inserted_id} has been created",
                }

    # search for cookies by username Note: this is written so that there is one cookie per user
    def get_cookie(self, user_name: str) -> dict:
        """retrieves a cookie doc from the db

        :param user_name: unique username of user
        :type user_name: str

        :rtype: dict[str, str], response status and reason or
        cookie doc
        """
        doc = self.db[COOKIE_COL].find_one(dict([("user_name", user_name)]))
        # if there are no cookies associated return error
        if doc is None:
            return {
                "status": "Failed",
                "reason": f"There is no cookie associated with user name: {user_name}",
            }
        else:
            return doc

    # deletes a cookie associated with a user. a cookie should be deleted and made at every login.
    def delete_cookie(self, user_name: str):
        """Deletes a cookie doc from the db

        :param user_name: unique username of user
        :type user_name: str

        :rtype: dict[str, str], response status and reason
        """
        doc = self.db[COOKIE_COL].find_one(dict([("user_name", user_name)]))

        # Check for a cookie associated with a user
        if doc is None:
            return {
                "status": "Failed",
                "reason": f"There is no cookie associated with user name: {user_name}",
            }
        # if nothing is returned from the deletion there is a problem with the db.
        else:
            ret = self.db[COOKIE_COL].delete_one(doc)
            if ret is None:
                return {
                    "status": "Failed",
                    "reason": "Something went wrong when deleting",
                }
            else:
                return {
                    "status": "Success",
                    "reason": f"Cookie has been deleted for user {user_name}",
                }

    # FOR TESTING PURPOSES ONLY - deletes all documents in the collection
    def delete_all_files(self):
        """Deletes all file documents from the db"""
        self.db[FILE_COL].delete_many({})

    def delete_all_repos(self):
        """Deletes all repo documents from the db"""
        self.db[REPO_COL].delete_many({})

    def delete_all_functions(self):
        """Deletes all function documents from the db"""
        self.db[FUNC_COL].delete_many({})
