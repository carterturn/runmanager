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
import tokenize
import os

import labscript_utils.shot_utils

from runmanager.evaluator import evaluate_globals

def _ensure_str(s):
    """convert bytestrings and numpy strings to python strings"""
    return s.decode() if isinstance(s, bytes) else str(s)


def is_valid_python_identifier(name):
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


def is_valid_group_name(name):
    """Ensure that a string is a valid name for a group.

    For backwards compatibility, group names must be valid hdf5 group names.
    The names of hdf5 groups may only contain ASCII characters. Furthermore, the
    characters "/" and "." are not allowed.
    New formats should allow these names as well.

    Args:
        name (str): The potential name for an hdf5 group.

    Returns:
        bool: Whether or not `name` is a valid name for an hdf5 group. This will
            be `True` if it is a valid name or `False` otherwise.
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

class GroupManager(object):
    """Class for managing many groups of labscript globals.

    The GroupManager class primarily manages opening, accessing, and closing group files.
    """

    def __init__(self):
        self.globals_files = {}

    def get_file(self, filename):
        """Retrieves globals file object.

        Raises KeyError if globals file is not open.
        """
        if filename in self.globals_files:
            return self.globals_files[filename]
        else:
            raise KeyError(f'{filename} is not an open globals file')

    def __getitem__(self, key):
        return self.get_file(key)

    def __contains__(self, key):
        return key in self.globals_files.keys()

    def open_file(self, filename):
        """Opens a globals file.

        Uses extension to decide which globals file class to call,
        and constructs an instance of that class.

        Supported extensions:
        	h5, for HDF5 file
        Raises ValueError for unsupported extension.
        """
        if filename in self.globals_files.keys():
            return self.globals_files[filename]
        file_class = _get_globals_file_subclass(filename)
        self.globals_files[filename] = file_class(filename)
        return self.globals_files[filename]

    def new_file(self, filename):
        """Creates a new globals file.

        Uses extension to decide which globals file class to call,
        and constructs an instance of that class with "new" set to true.

        Supported extensions:
        	h5, for HDF5 file
        Raises ValueError for unsupported extension.
        """
        if filename in self.globals_files.keys():
            return self.globals_files[filename]
        file_class = _get_globals_file_subclass(filename)
        self.globals_files[filename] = file_class(filename, new=True)
        return self.globals_files[filename]

    def copy_group(self, source_file, source_groupname, dest_file, delete_source_group=False):
        """ This function copies the group source_groupname from source_globals_file
        to dest_globals_file and renames the new group so that there is no name
        collision.

        Both source_file and dest_file must be currently open groups

        If delete_source_group is False the copied files have a suffix '_copy'.
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

    def close_file(self, filename):
        """Closes globals file.

        Raises KeyError if globals file is not open.
        """
        if filename in self.globals_files:
            del self.globals_files[filename]
        else:
            raise KeyError(f'{filename} is not an open globals file')

    def get_globals(self, active_groups):
        """Takes a dictionary of {group name: group file} and pulls the
        globals out of the groups in their files.  The globals are strings
        storing python expressions at this point. All these globals are
        packed into a new dictionary, keyed by group_name, where the values
        are dictionaries which look like {global_name: (expression, units, expansion), ...}"""
        # Produce list of groups for each global file
        groups_files = {}
        for global_group, global_file in active_groups.items():
            if global_file in groups_files.keys():
                groups_files[global_file].append(global_group)
            else:
                groups_files[global_file] = [global_group]
        sequence_globals = {}
        for group_file, group_list in groups_files.items():
            sequence_globals.update(self.get_file(group_file).get_globals(group_list))
        return sequence_globals

class GlobalsFile(object):
    """(Abstract) class representing a labscript globals file.

    GlobalsFile objects contain many labscript globals groups,
    and provides means to create, access, and destroy the groups.
    """
    def __init__(self, filename):
        self.filename = filename

    def _get_grouplist(self):
        raise NotImplementedError('get_grouplist not implemented')

    def get_grouplist(self):
        """Retrieve a list of group (names) in this globals file.
        """
        return self._get_grouplist()

    def _new_group(self, group_name):
        raise NotImplementedError('new_group not implemented')

    def new_group(self, group_name):
        """Creates a new, empty group object with name group_name and adds it to this file.
        """
        if not is_valid_group_name(group_name):
            raise ValueError(
                'Invalid group name. Group names must contain only ASCII '
                'characters and cannot include "/" or ".".'
            )
        self._new_group(group_name)

    def _rename_group(self, oldgroupname, newgroupname):
        raise NotImplementedError('rename_group not implemented')

    def rename_group(self, oldgroupname, newgroupname):
        """Rename group from oldgroupname to newgroupname.
        """
        if oldgroupname == newgroupname:
            return
        if not is_valid_group_name(newgroupname):
            raise ValueError(
                'Invalid group name. Group names must contain only ASCII '
                'characters and cannot include "/" or ".".'
            )
        self._rename_group(oldgroupname, newgroupname)

    def _delete_group(self, groupname):
        raise NotImplementedError('delete_group not implemented')

    def delete_group(self, groupname):
        """Delete group named groupname.
        """
        self._delete_group(groupname)

    def _get_group(self, groupname):
        raise NotImplementedError('get_group not implemented')

    def get_group(self, groupname):
        """Retrieve a GlobalsGroup corresponding to name groupname
        """
        return self._get_group(groupname)

    def __getitem__(self, key):
        return self.get_group(key)

    def __contains__(self, key):
        return key in self.get_grouplist()

    def _get_globalslist(self, groupname):
        raise NotImplementedError('get_globalslist not implemented')

    def _get_globals(self, group_names):
        raise NotImplementedError('get_globals not implemented')

    def get_globals(self, group_names):
        """Takes a list of group_names and pulls the
        globals out of the groups in their files.  The globals are strings
        storing python expressions at this point. All these globals are
        packed into a new dictionary, keyed by group_name, where the values
        are dictionaries which look like {global_name: (expression, units, expansion), ...}"""
        return self._get_globals(group_names)

class H5GlobalsFile(GlobalsFile):
    """GlobalsFile implementation for h5 files.
    """
    def __init__(self, filename, new=False):
        if new:
            with h5py.File(filename, 'w') as f:
                f.create_group('globals')
        super().__init__(filename)

    def _add_expansion_groups(self):
        """backward compatability, for globals files which don't have
        expansion groups. Create them if they don't exist. Guess expansion
        settings based on datatypes, if possible."""
        # DEPRECATED
        # Don't open in write mode unless we have to:
        with h5py.File(self.filename, 'r') as f:
            requires_expansion_group = []
            for groupname in f['globals']:
                group = f['globals'][groupname]
                if 'expansion' not in group:
                    requires_expansion_group.append(groupname)
        if requires_expansion_group:
            group_globalslists = [self.get_globalslist(groupname) for groupname in requires_expansion_group]
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

    def _get_grouplist(self):
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

    def _new_group(self, group_name):
        with h5py.File(self.filename, 'a') as f:
            if group_name in f['globals']:
                raise Exception('Can\'t create group: target name already exists.')
            group = f['globals'].create_group(group_name)
            group.create_group('units')
            group.create_group('expansion')

    def _rename_group(self, oldgroupname, newgroupname):
        with h5py.File(self.filename, 'a') as f:
            if newgroupname in f['globals']:
                raise Exception('Can\'t rename group: target name already exists.')
            f.copy(f['globals'][oldgroupname], '/globals/%s' % newgroupname)
            del f['globals'][oldgroupname]

    def _delete_group(self, groupname):
        with h5py.File(self.filename, 'a') as f:
            del f['globals'][groupname]

    def _get_group(self, groupname):
        with h5py.File(self.filename, 'r') as f:
            group = f['globals'][groupname]
        return GlobalsGroup(groupname, self)

    def _get_groups(self, group_names):
        with h5py.File(self.filename, 'r') as f:
            group = f['globals'][groupname]
        return GlobalsGroup(groupname, self)

    def _get_globalslist(self, groupname):
        with h5py.File(self.filename, 'r') as f:
            group = f['globals'][groupname]
            # File closes after this function call, so have to convert
            # the attrs to a dict before its file gets dereferenced:
            return dict(group.attrs)

    def _new_global(self, groupname, globalname):
        with h5py.File(self.filename, 'a') as f:
            group = f['globals'][groupname]
            if globalname in group.attrs:
                raise Exception('Can\'t create global: target name already exists.')
            group.attrs[globalname] = ''
            f['globals'][groupname]['units'].attrs[globalname] = ''
            f['globals'][groupname]['expansion'].attrs[globalname] = ''

    def _delete_global(self, groupname, globalname):
        with h5py.File(self.filename, 'a') as f:
            group = f['globals'][groupname]
            del group.attrs[globalname]
            del group['units'].attrs[globalname]
            del group['expansion'].attrs[globalname]

    def _get_value(self, groupname, globalname):
        with h5py.File(self.filename, 'r') as f:
            value = f['globals'][groupname].attrs[globalname]
            # Replace numpy strings with python unicode strings.
            # DEPRECATED, for backward compat with old files
            value = _ensure_str(value)
            return value

    def _set_value(self, groupname, globalname, value):
        with h5py.File(self.filename, 'a') as f:
            f['globals'][groupname].attrs[globalname] = value

    def _get_units(self, groupname, globalname):
        with h5py.File(self.filename, 'r') as f:
            value = f['globals'][groupname]['units'].attrs[globalname]
            # Replace numpy strings with python unicode strings.
            # DEPRECATED, for backward compat with old files
            value = _ensure_str(value)
            return value

    def _set_units(self, groupname, globalname, units):
        with h5py.File(self.filename, 'a') as f:
            f['globals'][groupname]['units'].attrs[globalname] = units

    def _get_expansion(self, groupname, globalname):
        with h5py.File(self.filename, 'r') as f:
            value = f['globals'][groupname]['expansion'].attrs[globalname]
            # Replace numpy strings with python unicode strings.
            # DEPRECATED, for backward compat with old files
            value = _ensure_str(value)
            return value

    def _set_expansion(self, groupname, globalname, expansion):
        with h5py.File(self.filename, 'a') as f:
            f['globals'][groupname]['expansion'].attrs[globalname] = expansion

    def _get_globals(self, group_names):
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

class GlobalsGroup(object):
    def __init__(self, name, parent_file):
        self.name = name
        self.parent_file = parent_file

    def get_filename(self):
        return self.parent_file.filename

    def get_globalslist(self):
        """Get a list of globals in this group."""
        return self.parent_file._get_globalslist(self.name)

    def rename(self, new_name):
        self.parent_file.rename_group(self.name, new_name)
        self.name = new_name

    def new_global(self, globalname):
        """Create a new global in this group with name globalname."""
        if not is_valid_python_identifier(globalname):
            raise ValueError('%s is not a valid Python variable name' % globalname)
        self.parent_file._new_global(self.name, globalname)

    def rename_global(self, oldglobalname, newglobalname):
        """Rename global from oldglobalname to newglobalname."""
        if oldglobalname == newglobalname:
            # No rename!
            return
        self.new_global(newglobalname)
        self.set_value(newglobalname, self.get_value(oldglobalname))
        self.set_units(newglobalname, self.get_units(oldglobalname))
        self.set_expansion(newglobalname, self.get_expansion(oldglobalname))
        self.delete_global(oldglobalname)

    def get_globals(self):
        """Retrieve all globals from the group."""
        group_globals = {}
        for global_name in self.get_globalslist():
            group_globals[global_name] = (self.get_value(global_name),
                                          self.get_units(global_name),
                                          self.get_expansion(global_name))
        return group_globals

    def get_value(self, globalname):
        """Get value of global named globalname."""
        return self.parent_file._get_value(self.name, globalname)

    def set_value(self, globalname, value):
        """Set value of global named globalname to value."""
        return self.parent_file._set_value(self.name, globalname, value)

    def get_units(self, globalname):
        """Get units of global named globalname."""
        return self.parent_file._get_units(self.name, globalname)

    def set_units(self, globalname, units):
        """Set units of global named globalname to units."""
        return self.parent_file._set_units(self.name, globalname, units)

    def get_expansion(self, globalname):
        """Get expansion of global named globalname."""
        return self.parent_file._get_expansion(self.name, globalname)

    def set_expansion(self, globalname, expansion):
        """Set expansion of global named globalname to expansion."""
        return self.parent_file._set_expansion(self.name, globalname, expansion)

    def delete_global(self, globalname):
        """Delete global named globalname."""
        self.parent_file._delete_global(self.name, globalname)

def guess_expansion_type(value):
    if isinstance(value, np.ndarray) or isinstance(value, list):
        return u'outer'
    else:
        return u''

def _get_globals_file_subclass(filename):
    """Create the appropriate sub-class of GlobalsFile based on the filename.
    """
    _, extension = os.path.splitext(filename)
    if extension == '.h5':
        return H5GlobalsFile
    else:
        raise ValueError(f'Extension "{extension}" not supported')

def get_shot_globals(filepath):
    """Returns the evaluated globals for a shot, for use by labscript or lyse.
    Simple dictionary access as in dict(h5py.File(filepath).attrs) would be fine
    except we want to apply some hacks, so it's best to do that in one place.
    
    Deprecated: use identical function `labscript_utils.shot_utils.get_shot_globals`
    """
    
    warnings.warn(
        FutureWarning("get_shot_globals has moved to labscript_utils.shot_utils. "
                      "Please update your code to import it from there."))

    return labscript_utils.shot_utils.get_shot_globals(filepath)
