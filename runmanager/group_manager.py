#####################################################################
#                                                                   #
# __main__.py                                                       #
#                                                                   #
# Copyright 2013, Monash University                                 #
#                                                                   #
# This file is part of the program runmanager, in the labscript     #
# suite (see http://labscriptsuite.org), and is licensed under the  #
# Simplified BSD License. See the license.txt file in the root of   #
# the project for the full license.                                 #
#                                                                   #
#####################################################################
"""The group manager class

Maintains a list of group files and groups within them.
Groups can be activated, opened, and accessed via this class.
"""

import io
import h5py
import numpy as np
import threading
import tokenize
import os
import warnings
import yaml
from typing import Any, Dict, List, Optional, Tuple, Union

import labscript_utils.shot_utils

from runmanager.evaluator import evaluate_globals

def _ensure_str(s) -> str:
    """Convert bytestrings and numpy strings to python strings.

    Args:
        s: The input string or bytes-like object to convert.
    Returns:
        A Python string representation of the input.
    """
    return s.decode() if isinstance(s, bytes) else str(s)


def is_valid_python_identifier(name: str) -> bool:
    """Check if a string is a valid Python identifier.

    Args:
        name: The string to check.
    Returns:
        True if the string is a valid Python identifier, False otherwise.
    """
    # No whitespace allowed. Do this check here because an actual newline in the source
    # is not easily distinguished from a NEWLINE token in the produced tokens, which is
    # produced even when there is no newline character in the string. So since we ignore
    # NEWLINE later, we must check for it now.
    if name != "".join(name.split()):
        return False
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(name).readline))
    except tokenize.TokenError:
        return False
    token_types = [
        t[0] for t in tokens if t[0] not in [tokenize.NEWLINE, tokenize.ENDMARKER]
    ]
    if len(token_types) == 1:
        return token_types[0] == tokenize.NAME
    return False


def is_valid_group_name(name: str) -> bool:
    """Ensure that a string is a valid name for a group.

    For backwards compatibility, group names must be valid hdf5 group names.
    The names of hdf5 groups may only contain ASCII characters. Furthermore, the
    characters "/" and "." are not allowed.
    New formats should allow these names as well.

    Args:
        name (str): The potential name for a group.
    Returns:
        bool: Whether or not `name` is a valid name for a group.
    """    
    # Ensure only ASCII characters are used.
    for char in name:
        if ord(char) >= 128:
            return False
    
    # Ensure forbidden ASCII characters are not used.
    forbidden_characters = ['.', '/']
    for character in forbidden_characters:
        if character in name:
            return False
    return True

class GlobalsGroup(object):
    """Represents a group within a globals file."""
    def __init__(self, name: str, parent_file: Any) -> None:
        """Initialize the GlobalsGroup.

        Args:
            name: The name of the group.
            parent_file: The parent GlobalsFile object.
        """
        self.name = name
        self.parent_file = parent_file

    def get_filename(self) -> str:
        """Get the filename of the parent file.

        Returns:
            str: The filename of the parent file.
        """
        return self.parent_file.filename

    def get_globalslist(self) -> List[str]:
        """Get a list of globals in this group.

        Returns:
            A list of global names in the group.
        """
        return self.parent_file._get_globalslist(self.name)

    def rename(self, new_name: str) -> None:
        """Rename this group.

        Args:
            new_name: The new name for the group.
        """
        self.parent_file.rename_group(self.name, new_name)
        self.name = new_name

    def new_global(self, globalname: str) -> None:
        """Create a new global in this group with name globalname.

        Args:
            globalname: The name for the new global.
        Raises:
            ValueError: If the global name is not a valid Python identifier.
        """
        if not is_valid_python_identifier(globalname):
            raise ValueError('%s is not a valid Python variable name' % globalname)
        self.parent_file._new_global(self.name, globalname)

    def rename_global(self, oldglobalname: str, newglobalname: str) -> None:
        """Rename global from oldglobalname to newglobalname.

        Args:
            oldglobalname: The current name of the global.
            newglobalname: The new name for the global.
        """
        if oldglobalname == newglobalname:
            # No rename!
            return
        self.new_global(newglobalname)
        self.set_value(newglobalname, self.get_value(oldglobalname))
        self.set_units(newglobalname, self.get_units(oldglobalname))
        self.set_expansion(newglobalname, self.get_expansion(oldglobalname))
        self.delete_global(oldglobalname)

    def get_globals(self) -> Dict[str, Tuple[str, str, str]]:
        """Retrieve all globals from the group.

        Returns:
            A dictionary mapping global names to tuples of (value, units, expansion).
        """
        group_globals = self.parent_file._get_globals([self.name])
        return group_globals[self.name]

    def get_value(self, globalname: str) -> str:
        """Get value of global named globalname.

        Args:
            globalname: The name of the global.
        Returns:
            str: The value of the global.
        """
        return self.parent_file._get_value(self.name, globalname)

    def set_value(self, globalname: str, value: str) -> None:
        """Set value of global named globalname to value.

        Args:
            globalname: The name of the global.
            value: The string value to set.
        """
        return self.parent_file._set_value(self.name, globalname, value)

    def get_units(self, globalname: str) -> str:
        """Get units of global named globalname.

        Args:
            globalname: The name of the global.
        Returns:
            str: The units of the global.
        """
        return self.parent_file._get_units(self.name, globalname)

    def set_units(self, globalname: str, units: str) -> None:
        """Set units of global named globalname to units.

        Args:
            globalname: The name of the global.
            units: The string units to set.
        """
        return self.parent_file._set_units(self.name, globalname, units)

    def get_expansion(self, globalname: str) -> str:
        """Get expansion of global named globalname.

        Args:
            globalname: The name of the global.
        Returns:
            str: The expansion of the global.
        """
        return self.parent_file._get_expansion(self.name, globalname)

    def set_expansion(self, globalname: str, expansion: str) -> None:
        """Set expansion of global named globalname to expansion.

        Args:
            globalname: The name of the global.
            expansion: The string expansion to set.
        """
        return self.parent_file._set_expansion(self.name, globalname, expansion)

    def delete_global(self, globalname: str) -> None:
        """Delete global named globalname.

        Args:
            globalname: The name of the global to delete.
        """
        self.parent_file._delete_global(self.name, globalname)

class GlobalsFile(object):
    """(Abstract) class representing a labscript globals file.

    GlobalsFile objects contain many labscript globals groups,
    and provides means to create, access, and destroy the groups.
    """
    def __init__(self, filename: str) -> None:
        """Initialize the GlobalsFile with a filename.

        Args:
            filename: The path to the globals file.
        """
        self.filename = filename

    def _get_grouplist(self) -> List[str]:
        """Retrieve a list of group names in this globals file.

        This method should be implemented by subclasses.

        Raises:
            NotImplementedError: If not overridden by a subclass.
        """
        raise NotImplementedError('get_grouplist not implemented')

    def get_grouplist(self) -> List[str]:
        """Retrieve a list of group (names) in this globals file.

        Returns:
            A list of group names in the file.
        """
        return self._get_grouplist()

    def _new_group(self, group_name: str) -> None:
        """Create a new group within this file.

        This method should be implemented by subclasses.

        Raises:
            NotImplementedError: If not overridden by a subclass.
        """
        raise NotImplementedError('new_group not implemented')

    def new_group(self, group_name: str) -> None:
        """Creates a new, empty group object with name group_name and adds it to this file.

        Args:
            group_name: The name for the new group.
        Raises:
            ValueError: If the group name is invalid.
        """
        if not is_valid_group_name(group_name):
            raise ValueError(
                'Invalid group name. Group names must contain only ASCII '
                'characters and cannot include "/" or ".".'
            )
        self._new_group(group_name)

    def _rename_group(self, oldgroupname: str, newgroupname: str) -> None:
        """Rename a group within this file.

        This method should be implemented by subclasses.

        Raises:
            NotImplementedError: If not overridden by a subclass.
        """
        raise NotImplementedError('rename_group not implemented')

    def rename_group(self, oldgroupname: str, newgroupname: str) -> None:
        """Rename group from oldgroupname to newgroupname.

        Args:
            oldgroupname: The current name of the group.
            newgroupname: The new name for the group.
        Raises:
            ValueError: If the new group name is invalid.
        """
        if oldgroupname == newgroupname:
            return
        if not is_valid_group_name(newgroupname):
            raise ValueError(
                'Invalid group name. Group names must contain only ASCII '
                'characters and cannot include "/" or ".".'
            )
        self._rename_group(oldgroupname, newgroupname)

    def _delete_group(self, groupname: str) -> None:
        """Delete a group within this file.

        This method should be implemented by subclasses.

        Raises:
            NotImplementedError: If not overridden by a subclass.
        """
        raise NotImplementedError('delete_group not implemented')

    def delete_group(self, groupname: str) -> None:
        """Delete group named groupname.

        Args:
            groupname: The name of the group to delete.
        """
        self._delete_group(groupname)

    def _get_group(self, groupname: str) -> GlobalsGroup:
        """Retrieve a group object by name.

        This method should be implemented by subclasses.

        Raises:
            NotImplementedError: If not overridden by a subclass.
        """
        raise NotImplementedError('get_group not implemented')

    def get_group(self, groupname: str) -> GlobalsGroup:
        """Retrieve a GlobalsGroup corresponding to name groupname

        Args:
            groupname: The name of the group to retrieve.
        Returns:
            GlobalsGroup: The group object.
        """
        return self._get_group(groupname)

    def __getitem__(self, key: str) -> GlobalsGroup:
        """Retrieve a group using subscript notation.

        Args:
            key: The name of the group to retrieve.
        Returns:
            GlobalsGroup: The group object.
        """
        return self.get_group(key)

    def __contains__(self, key: str) -> bool:
        """Check if a group exists in the file.

        Args:
            key: The group name to check.
        Returns:
            True if the group exists, False otherwise.
        """
        return key in self.get_grouplist()

    def _get_globalslist(self, groupname: str) -> List[str]:
        """Get a list of global names within a group.

        This method should be implemented by subclasses.

        Raises:
            NotImplementedError: If not overridden by a subclass.
        """
        raise NotImplementedError('get_globalslist not implemented')

    def _get_globals(self, group_names: List[str]) -> Dict[str, Dict[str, Tuple[str, str, str]]]:
        """Get all globals from specified groups.

        This method should be implemented by subclasses.

        Raises:
            NotImplementedError: If not overridden by a subclass.
        """
        raise NotImplementedError('get_globals not implemented')

    def get_globals(self, group_names: List[str]) -> Dict[str, Dict[str, Tuple[str, str, str]]]:
        """Takes a list of group_names and pulls the
        globals out of the groups in their files.  The globals are strings
        storing python expressions at this point. All these globals are
        packed into a new dictionary, keyed by group_name, where the values
        are dictionaries which look like {global_name: (expression, units, expansion), ...}

        Args:
            group_names: A list of group names to retrieve globals from.
        Returns:
            A dictionary with group names as keys and dictionaries of globals
            as values. Each global entry is a tuple of (expression, units, expansion).
        """
        return self._get_globals(group_names)

class GroupManager(object):
    """Class for managing many groups of labscript globals.

    The GroupManager class primarily manages opening, accessing, and closing group files.
    """

    def __init__(self) -> None:
        """Initialize the GroupManager with an empty dictionary of globals files."""
        self.globals_files = {}

    def get_file(self, filename: str) -> GlobalsFile:
        """Retrieves globals file object.

        Args:
            filename: The filename of the open globals file.
        Returns:
            GlobalsFile: The globals file object associated with the filename.
        Raises:
            KeyError: If the globals file is not open.
        """
        if filename in self.globals_files:
            return self.globals_files[filename]
        else:
            raise KeyError(f'{filename} is not an open globals file')

    def __getitem__(self, key: str) -> GlobalsFile:
        """Retrieve a globals file.

        Args:
            key: The filename of the globals file to retrieve.
        Returns:
            GlobalsFile: The globals file object.
        Raises:
            KeyError: If the file is not open.
        """
        return self.get_file(key)

    def __contains__(self, key: str) -> bool:
        """Check if a file is open using the 'in' operator.

        Args:
            key: The filename to check.
        Returns:
            True if the file is open, False otherwise.
        """
        return key in self.globals_files.keys()

    def open_file(self, filename: str) -> GlobalsFile:
        """Opens a globals file.

        Uses extension to decide which globals file class to call,
        and constructs an instance of that class.

        Supported extensions:
            h5, for HDF5 file
            yaml, yml for YAML file
        Raises ValueError for unsupported extension.

        Args:
            filename: The path to the globals file to open.
        Returns:
            GlobalsFile: The opened globals file object.
        Raises:
            KeyError: If the file is already open.
            ValueError: If the file extension is not supported.
        """
        if filename in self.globals_files.keys():
            return self.globals_files[filename]
        file_class = _get_globals_file_subclass(filename)
        self.globals_files[filename] = file_class(filename)
        return self.globals_files[filename]

    def new_file(self, filename: str) -> GlobalsFile:
        """Creates a new globals file.

        Uses extension to decide which globals file class to call,
        and constructs an instance of that class with "new" set to true.

        Supported extensions:
            h5, for HDF5 file
            yaml, yml for YAML file
        Raises ValueError for unsupported extension.

        Args:
            filename: The path to the new globals file to create.
        Returns:
            GlobalsFile: The newly created globals file object.
        Raises:
            KeyError: If the file is already open.
            ValueError: If the file extension is not supported.
        """
        if filename in self.globals_files.keys():
            return self.globals_files[filename]
        file_class = _get_globals_file_subclass(filename)
        self.globals_files[filename] = file_class(filename, new=True)
        return self.globals_files[filename]

    def copy_group(self, source_file: str, source_groupname: str,
                   dest_file: Optional[str] = None, delete_source_group: bool = False) -> str:
        """Copy a group from one file to another.

        This function copies the group source_groupname from source_globals_file
        to dest_globals_file and renames the new group so that there is no name
        collision.

        Both source_file and dest_file must be currently open groups.

        If delete_source_group is False the copied files have a suffix '_copy'.

        Args:
            source_file: The filename of the source globals file.
            source_groupname: The name of the group to copy.
            dest_file: The filename of the destination globals file.
                If None, uses the source file.
            delete_source_group: If True, delete the source group after 
        Returns:
            str: The name of the newly created destination group.
        Raises:
            KeyError: If either source_file or dest_file is not open.
        """
        if dest_file is None:
            dest_file = source_file
        if source_file == dest_file and delete_source_group:
            # If copying to the same file with a delete, do nothing.
            return source_groupname

        # Rename Group until there is no name collisions
        i = 0 if not delete_source_group else 1
        dest_groupname = source_groupname
        while dest_groupname in self.globals_files[dest_file].get_grouplist():
            dest_groupname = "{}({})".format(dest_groupname, i) if i > 0 else "{}_copy".format(dest_groupname)
            i += 1

        # Do the copy
        source_group = self.globals_files[source_file][source_groupname]
        self.globals_files[dest_file].new_group(dest_groupname)
        dest_group = self.globals_files[dest_file][dest_groupname]
        for global_name, (value, units, expansion) in source_group.get_globals().items():
            dest_group.new_global(global_name)
            dest_group.set_value(global_name, value)
            dest_group.set_units(global_name, units)
            dest_group.set_expansion(global_name, expansion)

        return dest_groupname

    def close_file(self, filename: str) -> None:
        """Closes globals file.

        Args:
            filename: The filename of the globals file to close.
        Raises:
            KeyError: If the globals file is not open.
        """
        if filename in self.globals_files:
            del self.globals_files[filename]
        else:
            raise KeyError(f'{filename} is not an open globals file')

    def get_globals(self, active_groups: Dict[str, str]) -> Dict[str, Dict[str, Tuple[str, str, str]]]:
        """Takes a dictionary of {group name: group filename} and pulls the
        globals out of the groups in their files.  The globals are strings
        storing python expressions at this point. All these globals are
        packed into a new dictionary, keyed by group_name, where the values
        are dictionaries which look like {global_name: (expression, units, expansion), ...}

        Args:
            active_groups: A dictionary mapping group names to their group files.
        Returns:
            A dictionary with group names as keys and dictionaries of globals
            as values. Each global entry is a tuple of (expression, units, expansion).
        """
        # First, produce list of groups for each global file
        groups_files = {}
        for global_group, global_file in active_groups.items():
            if global_file in groups_files.keys():
                groups_files[global_file].append(global_group)
            else:
                groups_files[global_file] = [global_group]
        # Next, get globals for each file and combine into large dictionary
        sequence_globals = {}
        for group_file, group_list in groups_files.items():
            sequence_globals.update(self.get_file(group_file).get_globals(group_list))
        return sequence_globals

class H5GlobalsFile(GlobalsFile):
    """GlobalsFile implementation for h5 files."""
    def __init__(self, filename: str, new: bool = False) -> None:
        """Initialize the H5GlobalsFile.

        Args:
            filename: The path to the HDF5 file.
            new: If True, create a new file with a 'globals' group.
                If False, open an existing file.
        """
        if new:
            with h5py.File(filename, 'w') as f:
                f.create_group('globals')
        super().__init__(filename)

    def _add_expansion_groups(self) -> None:
        """Add expansion groups for backward compatibility.

        This method adds 'expansion' settings to globals files which don't have
        them, creating them if they don't exist. It guesses expansion
        settings based on datatypes, if possible.

        Note:
            This is deprecated functionality.
        """
        # DEPRECATED
        # Don't open in write mode unless we have to:
        with h5py.File(self.filename, 'r') as f:
            requires_expansion_group: List[str] = []
            for groupname in f['globals']:
                group = f['globals'][groupname]
                if 'expansion' not in group:
                    requires_expansion_group.append(groupname)
        if requires_expansion_group:
            group_globalslists: List[List[str]] = [self.get_globalslist(groupname) for groupname in requires_expansion_group]
            with h5py.File(self.filename, 'a') as f:
                for groupname, globalslist in zip(requires_expansion_group, group_globalslists):
                    group = f['globals'][groupname]
                    subgroup = group.create_group('expansion')
                    # Initialise all expansion settings to blank strings:
                    for name in globalslist:
                        subgroup.attrs[name] = ''
            groups = {group_name: self.filename for group_name in get_grouplist(self.filename)}
            sequence_globals = self.get_globals(groups)
            evaled_globals, global_hierarchy, expansions = evaluate_globals(sequence_globals, raise_exceptions=False)
            for group_name in evaled_globals:
                for global_name in evaled_globals[group_name]:
                    value = evaled_globals[group_name][global_name]
                    expansion = guess_expansion_type(value)
                    self.get_group(group_name).set_expansion(global_name, expansion)

    def _get_grouplist(self) -> List[str]:
        """Retrieve a list of group names in this HDF5 file.

        For backward compatibility, this method adds 'expansion' settings to this
        globals file, if it doesn't contain any. It guesses expansion settings
        if possible.

        Returns:
            A list of group names in the file.
        """
        # For backward compatability, add 'expansion' settings to this
        # globals file, if it doesn't contain any.  Guess expansion settings
        # if possible.
        # DEPRECATED
        self._add_expansion_groups()

        with h5py.File(self.filename, 'r') as f:
            grouplist = f['globals']
            # File closes after this function call, so have to
            # convert the grouplist generator to a list of strings
            # before its file gets dereferenced:
            return list(grouplist)

    def _new_group(self, group_name: str) -> None:
        """Create a new group in the HDF5 file.

        Args:
            group_name: The name for the new group.
        Raises:
            Exception: If a group with the given name already exists.
        """
        with h5py.File(self.filename, 'a') as f:
            if group_name in f['globals']:
                raise Exception('Can\'t create group: target name already exists.')
            group = f['globals'].create_group(group_name)
            group.create_group('units')
            group.create_group('expansion')

    def _rename_group(self, oldgroupname: str, newgroupname: str) -> None:
        """Rename a group in the HDF5 file.

        Args:
            oldgroupname: The current name of the group.
            newgroupname: The new name for the group.
        Raises:
            Exception: If a group with the new name already exists.
        """
        with h5py.File(self.filename, 'a') as f:
            if newgroupname in f['globals']:
                raise Exception('Can\'t rename group: target name already exists.')
            f.copy(f['globals'][oldgroupname], '/globals/%s' % newgroupname)
            del f['globals'][oldgroupname]

    def _delete_group(self, groupname: str) -> None:
        """Delete a group from the HDF5 file.

        Args:
            groupname: The name of the group to delete.
        """
        with h5py.File(self.filename, 'a') as f:
            del f['globals'][groupname]

    def _get_group(self, groupname: str) -> GlobalsGroup:
        """Retrieve a group object by name.

        Args:
            groupname: The name of the group to retrieve.
        Returns:
            GlobalsGroup: object representing the group.
        """
        with h5py.File(self.filename, 'r') as f:
            group = f['globals'][groupname]
        return GlobalsGroup(groupname, self)

    def _get_globalslist(self, groupname: str) -> List[str]:
        """Get a list of global names within a group.

        Args:
            groupname: The name of the group.
        Returns:
            A list of global names in the group.
        """
        with h5py.File(self.filename, 'r') as f:
            group = f['globals'][groupname]
            # File closes after this function call, so have to convert
            # the attrs to a dict before its file gets dereferenced:
            return dict(group.attrs)

    def _new_global(self, groupname: str, globalname: str) -> None:
        """Create a new global attribute within a group.

        Args:
            groupname: The name of the group containing the global.
            globalname: The name of the new global.
        Raises:
            Exception: If a global with the given name already exists.
        """
        with h5py.File(self.filename, 'a') as f:
            group = f['globals'][groupname]
            if globalname in group.attrs:
                raise Exception('Can\'t create global: target name already exists.')
            group.attrs[globalname] = ''
            f['globals'][groupname]['units'].attrs[globalname] = ''
            f['globals'][groupname]['expansion'].attrs[globalname] = ''

    def _delete_global(self, groupname: str, globalname: str) -> None:
        """Delete a global attribute from a group.

        Args:
            groupname: The name of the group containing the global.
            globalname: The name of the global to delete.
        """
        with h5py.File(self.filename, 'a') as f:
            group = f['globals'][groupname]
            del group.attrs[globalname]
            del group['units'].attrs[globalname]
            del group['expansion'].attrs[globalname]

    def _get_value(self, groupname: str, globalname: str) -> str:
        """Get the value of a global.

        Args:
            groupname: The name of the group containing the global.
            globalname: The name of the global.
        Returns:
            str: The value of the global.
        """
        with h5py.File(self.filename, 'r') as f:
            value = f['globals'][groupname].attrs[globalname]
            # Replace numpy strings with python unicode strings.
            # DEPRECATED, for backward compat with old files
            value = _ensure_str(value)
            return value

    def _set_value(self, groupname: str, globalname: str, value: str) -> None:
        """Set the value of a global.

        Args:
            groupname: The name of the group containing the global.
            globalname: The name of the global.
            value: The string value to set.
        """
        with h5py.File(self.filename, 'a') as f:
            f['globals'][groupname].attrs[globalname] = value

    def _get_units(self, groupname: str, globalname: str) -> str:
        """Get the units of a global.

        Args:
            groupname: The name of the group containing the global.
            globalname: The name of the global.
        Returns:
            str: The units of the global.
        """
        with h5py.File(self.filename, 'r') as f:
            value = f['globals'][groupname]['units'].attrs[globalname]
            # Replace numpy strings with python unicode strings.
            # DEPRECATED, for backward compat with old files
            value = _ensure_str(value)
            return value

    def _set_units(self, groupname: str, globalname: str, units: str) -> None:
        """Set the units of a global.

        Args:
            groupname: The name of the group containing the global.
            globalname: The name of the global.
            units: The string units to set.
        """
        with h5py.File(self.filename, 'a') as f:
            f['globals'][groupname]['units'].attrs[globalname] = units

    def _get_expansion(self, groupname: str, globalname: str) -> str:
        """Get the expansion of a global.

        Args:
            groupname: The name of the group containing the global.
            globalname: The name of the global.
        Returns:
            str: The expansion of the global.
        """
        with h5py.File(self.filename, 'r') as f:
            value = f['globals'][groupname]['expansion'].attrs[globalname]
            # Replace numpy strings with python unicode strings.
            # DEPRECATED, for backward compat with old files
            value = _ensure_str(value)
            return value

    def _set_expansion(self, groupname: str, globalname: str, expansion: str) -> None:
        """Set the expansion of a global.

        Args:
            groupname: The name of the group containing the global.
            globalname: The name of the global.
            expansion: The string expansion to set.
        """
        with h5py.File(self.filename, 'a') as f:
            f['globals'][groupname]['expansion'].attrs[globalname] = expansion

    def _get_globals(self, group_names: List[str]) -> Dict[str, Dict[str, Tuple[str, str, str]]]:
        """Get all globals from specified groups.

        Args:
            group_names: A list of group names to retrieve globals from.
        Returns:
            A dictionary with group names as keys and dictionaries of globals
            as values. Each global entry is a tuple of (expression, units, expansion).
        """
        globals_dict = {}
        with h5py.File(self.filename, 'r') as f:
            for group_name in group_names:
                globals_dict[group_name] = {}
                globals_group = f['globals'][group_name]
                values = dict(globals_group.attrs)
                units = dict(globals_group['units'].attrs)
                expansions = dict(globals_group['expansion'].attrs)
                for global_name, value in values.items():
                    unit = units[global_name]
                    expansion = expansions[global_name]
                    # Replace numpy strings with python unicode strings.
                    # DEPRECATED, for backward compat with old files
                    value = _ensure_str(value)
                    unit = _ensure_str(unit)
                    expansion = _ensure_str(expansion)
                    globals_dict[group_name][global_name] = value, unit, expansion
        return globals_dict

class YamlGlobalsFile(GlobalsFile):
    """GlobalsFile implementation for yaml files.

    This class provides a YAML-based implementation of the GlobalsFile interface,
    allowing globals to be stored and loaded from YAML files.

    YAML structure:
    ```yaml
    globals:
      group_name:
        global_name_1:
          value: "expression"
          units: "units"
          expansion: "expansion"
    ```
    """
    def __init__(self, filename: str, new: bool = False) -> None:
        """Initialize the YamlGlobalsFile.

        Args:
            filename: The path to the YAML file.
            new: If True, create a new file. If False, open an existing file.
        """
        self.filename = filename
        self._data = {}
        self._last_read_time = None
        self._lock = threading.Lock()

        if new:
            # Create new YAML file with empty globals structure
            with open(self.filename, 'w') as f:
                yaml.dump({'globals': {}}, f)
            self._last_read_time = os.stat(self.filename).st_mtime_ns

    def _get_data(self) -> Dict[str, Any]:
        """Get data from YAML file (or cached version).

        Reads the YAML file only if it has changed since the last read.

        Returns:
            The cached data dictionary.
        """
        reload_data = False
        if self._last_read_time is None:
            reload_data = True
        else:
            if os.stat(self.filename).st_mtime_ns > self._last_read_time:
                reload_data = True
        if reload_data:
            with self._lock:
                with open(self.filename, 'r') as f:
                    self._data = yaml.safe_load(f)
                    self._last_read_time = os.stat(self.filename).st_mtime_ns
        return self._data

    def _set_data(self, data) -> None:
        """Set cached data and save to the YAML file.

        Args:
            data: The data dictionary to save.
        """
        self._data = data
        with self._lock:
            with open(self.filename, 'w') as f:
                yaml.dump(self._data, f)
            self._last_read_time = os.stat(self.filename).st_mtime_ns

    def _get_grouplist(self) -> List[str]:
        """Retrieve a list of group names from the YAML file.

        Returns:
            A list of group names in the file.
        Raises:
            KeyError: if this YAML file does not contain globals.
        """
        data = self._get_data()
        return list(data['globals'].keys())

    def _new_group(self, group_name: str) -> None:
        """Create a new group in the YAML file.

        Args:
            group_name: The name for the new group.
        """
        data = self._get_data()
        if group_name in data['globals']:
            raise Exception(f'Can\'t create group: target name already exists.')
        data['globals'][group_name] = {}
        self._set_data(data)

    def _rename_group(self, oldgroupname: str, newgroupname: str) -> None:
        """Rename a group in the YAML file.

        Args:
            oldgroupname: The current name of the group.
            newgroupname: The new name for the group.
        """
        data = self._get_data()
        if newgroupname in data['globals']:
            raise Exception(f'Can\'t rename group: target name already exists.')
        data['globals'][newgroupname] = data['globals'].pop(oldgroupname)
        self._set_data(data)

    def _delete_group(self, groupname: str) -> None:
        """Delete a group from the YAML file.

        Args:
            groupname: The name of the group to delete.
        """
        data = self._get_data()
        if groupname in data['globals']:
            del data['globals'][groupname]
        self._set_data(data)

    def _get_group(self, groupname: str) -> 'GlobalsGroup':
        """Retrieve a group object by name.

        Args:
            groupname: The name of the group to retrieve.
        Returns:
            A GlobalsGroup object representing the group.
        """
        return GlobalsGroup(groupname, self)

    def _get_globalslist(self, groupname: str) -> List[str]:
        """Get a list of global names within a group.

        Args:
            groupname: The name of the group.
        Returns:
            A list of global names in the group.
        """
        data = self._get_data()
        group_data = data['globals'].get(groupname, {})
        return list(group_data.keys())

    def _new_global(self, groupname: str, globalname: str) -> None:
        """Create a new global within a group.

        Args:
            groupname: The name of the group containing the global.
            globalname: The name of the new global.
        Raises:
            Exception: If a global with the given name already exists.
        """
        data = self._get_data()
        if groupname not in data['globals']:
            data['globals'][groupname] = {}
        if globalname in data['globals'][groupname]:
            raise Exception(f'Can\'t create global: target name already exists.')
        data['globals'][groupname][globalname] = {'value': '', 'units': '', 'expansion': ''}
        self._set_data(data)

    def _delete_global(self, groupname: str, globalname: str) -> None:
        """Delete a global from a group.

        Args:
            groupname: The name of the group containing the global.
            globalname: The name of the global to delete.
        """
        data = self._get_data()
        group_data = data['globals'][groupname]
        del data['globals'][groupname][globalname]
        self._set_data(data)

    def _get_value(self, groupname: str, globalname: str) -> str:
        """Get the value of a global.

        Args:
            groupname: The name of the group containing the global.
            globalname: The name of the global.
        Returns:
            str: The string value of the global.
        """
        data = self._get_data()
        return data['globals'][groupname][globalname]['value']

    def _set_value(self, groupname: str, globalname: str, value: str) -> None:
        """Set the value of a global.

        Args:
            groupname: The name of the group containing the global.
            globalname: The name of the global.
            value: The string value to set.
        """
        data = self._get_data()
        data['globals'][groupname][globalname]['value'] = value
        self._set_data(data)

    def _get_units(self, groupname: str, globalname: str) -> str:
        """Get the units of a global.

        Args:
            groupname: The name of the group containing the global.
            globalname: The name of the global.
        Returns:
            str: The string units of the global.
        """
        data = self._get_data()
        return data['globals'][groupname][globalname]['units']

    def _set_units(self, groupname: str, globalname: str, units: str) -> None:
        """Set the units of a global.

        Args:
            groupname: The name of the group containing the global.
            globalname: The name of the global.
            units: The string units to set.
        """
        data = self._get_data()
        data['globals'][groupname][globalname]['units'] = units
        self._set_data(data)

    def _get_expansion(self, groupname: str, globalname: str) -> str:
        """Get the expansion of a global.

        Args:
            groupname: The name of the group containing the global.
            globalname: The name of the global.
        Returns:
            str: The string expansion of the global.
        """
        data = self._get_data()
        return data['globals'][groupname][globalname]['expansion']

    def _set_expansion(self, groupname: str, globalname: str, expansion: str) -> None:
        """Set the expansion of a global.

        Args:
            groupname: The name of the group containing the global.
            globalname: The name of the global.
            expansion: The string expansion to set.
        """
        data = self._get_data()
        data['globals'][groupname][globalname]['expansion'] = expansion
        self._set_data(data)

    def _get_globals(self, group_names: List[str]) -> Dict[str, Dict[str, Tuple[str, str, str]]]:
        """Get all globals from specified groups.

        Args:
            group_names: A list of group names to retrieve globals from.
        Returns:
            A dictionary with group names as keys and dictionaries of globals
            as values. Each global entry is a tuple of (expression, units, expansion).
        """
        globals_dict = {}
        data = self._get_data()
        for group_name in group_names:
            globals_dict[group_name] = {}
            group_data = data['globals'][group_name]
            for global_name, global_data in group_data.items():
                globals_dict[group_name][global_name] = (str(global_data['value']),
                                                         str(global_data['units']),
                                                         str(global_data['expansion']))
        return globals_dict

def guess_expansion_type(value: Any) -> str:
    """Guess the expansion type based on the value's type.

    Args:
        value: The value to analyze.
    Returns:
        str: 'outer' if the value is a numpy array or list, otherwise empty string.
    """
    if isinstance(value, np.ndarray) or isinstance(value, list):
        return u'outer'
    else:
        return u''

def _get_globals_file_subclass(filename: str) -> type:
    """Create the appropriate sub-class of GlobalsFile based on the filename.

    Args:
        filename: The path to the globals file.
    Returns:
        type: The appropriate subclass of GlobalsFile.
    Raises:
        ValueError: If the file extension is not supported.
    """
    _, extension = os.path.splitext(filename)
    if extension == '.h5':
        return H5GlobalsFile
    elif extension in ['.yaml', '.yml']:
        return YamlGlobalsFile
    else:
        raise ValueError(f'Extension "{extension}" not supported')

def get_shot_globals(filepath: str) -> Dict[str, Any]:
    """Returns the evaluated globals for a shot, for use by labscript or lyse.

    Simple dictionary access as in dict(h5py.File(filepath).attrs) would be fine
    except we want to apply some hacks, so it's best to do that in one place.

    Note:
        Deprecated: use identical function `labscript_utils.shot_utils.get_shot_globals`
    Args:
        filepath: The path to the shot file.
    Returns:
        The evaluated globals dictionary.
    Raises:
        FutureWarning: Always raised to indicate this function is deprecated.
    """
    warnings.warn(
        FutureWarning("get_shot_globals has moved to labscript_utils.shot_utils. "
                      "Please update your code to import it from there."))

    return labscript_utils.shot_utils.get_shot_globals(filepath)
