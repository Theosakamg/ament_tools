# Copyright 2014 Open Source Robotics Foundation, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import argparse
import os
import re

from multiprocessing import cpu_count

from ament_package import package_exists_at
from ament_package import PACKAGE_MANIFEST_FILENAME


def argparse_existing_dir(path):
    if not os.path.exists(path):
        raise argparse.ArgumentTypeError("Path '%s' does not exist" % path)
    if not os.path.isdir(path):
        raise argparse.ArgumentTypeError("Path '%s' is not a directory" % path)
    return path


def argparse_existing_package(path):
    path = argparse_existing_dir(path)
    if not package_exists_at(path):
        raise argparse.ArgumentTypeError(
            "Path '%s' does not contain a '%s' file" %
            (path, PACKAGE_MANIFEST_FILENAME))
    return path


def determine_path_argument(cwd, base_path, argument, default):
    if argument is None:
        # if no argument is passed the default is relative to the base_path
        return os.path.join(base_path, default)
    # if an argument is passed it is relative to cwd (or absolute)
    return os.path.abspath(os.path.join(cwd, argument))


def extract_jobs_flags(arguments):
    """Extracts make job flags from a list of other make flags, i.e. -j8 -l8

    :param arguments: string of space separated arguments which may or may not
        contain make job flags
    :type arguments: str
    :returns: list of make jobs flags as a space separated string
    :rtype: str
    """
    regex = (
        r'(?:^|\s)(-?(?:j|l)(?:\s*[0-9]+|\s|$))'
        r'|'
        r'(?:^|\s)((?:--)?(?:jobs|load-average)(?:(?:=|\s+)[0-9]+|(?:\s|$)))'
    )
    matches = re.findall(regex, arguments) or []
    matches = [m[0] or m[1] for m in matches]
    return ' '.join([m.strip() for m in matches]) if matches else None


def combine_make_flags(make_flags, args, extras):
    """Combine make flags and arg's make job flags with make_flags in extras.

    :param list make_flags: existing make_flags, extracted from args already.
    :param list args: command line args with ``--make-flags ...`` extracted.
    :param dict extras: extras dict to which make flags are added/extended.
    """
    # Add make_flags in extras, if they exist, to verb's --make-flags
    make_flags += extras.get('make_flags', [])

    # Extract make job arguments from main arguments and add to make_flags
    make_job_flags = extract_jobs_flags(' '.join(args))
    if make_job_flags:
        args = re.sub(make_job_flags, '', ' '.join(args)).split()
        make_flags.extend(make_job_flags.split())

    # Ensure make args will have job flags and then store make_flags in extras
    extras['make_flags'] = ensure_make_job_flags(make_flags)
    return args


def ensure_make_job_flags(input_make_args):
    """Ensures that make will get correct job flags, either from args or env.

    If no job flags are present and there are none in the MAKEFLAGS environment
    variable, then make flags are set to the cpu_count, e.g. -j4 -l4.

    :param input_make_args: list of make arguments to be handled
    :type input_make_args: list
    :returns: copied list of make arguments, potentially with modifications
    :rtype: list
    """
    make_args = list(input_make_args)

    # If no -j/--jobs/-l/--load-average flags are in make_args
    if not extract_jobs_flags(' '.join(make_args)):
        # If -j/--jobs/-l/--load-average are in MAKEFLAGS
        if extract_jobs_flags(os.environ.get('MAKEFLAGS', "")):
            # Do not extend make arguments, let MAKEFLAGS set things
            pass
        else:
            # Else extend the make_arguments to include some jobs flags
            # Use the number of CPU cores
            try:
                jobs = cpu_count()
                make_args.append('-j{0}'.format(jobs))
                make_args.append('-l{0}'.format(jobs))
            except NotImplementedError:
                # If the number of cores cannot be determined,
                # then do not extend args
                pass
    return make_args


def extract_argument_group(args, delimiting_option):
    """Extract a group of arguments from a list of arguments using a delimeter.

    Here is an example:

    .. code-block:: python

        >>> extract_argument_group(['foo', '--args', 'bar', '--baz'], '--args')
        (['foo'], ['bar', '--baz'])

    The group can always be endded using the double hyphen ``--``.
    In order to pass a double hyphen as arguments, use three hyphens ``---``.
    Any set of hypens encountered after the delimeter, and up to ``--``, which
    have three or more hyphens and are isolated, will be captured and reduced
    by one hyphen.

    For example:

    .. code-block:: python

        >> extract_argument_group(['foo',
                                   '--args', 'bar', '--baz', '---', '--',
                                   '--foo-option'], '--args')
        (['foo', '--foo-option'], ['bar', '--baz', '--'])

    In the result the ``--`` comes from the ``---`` in the input.
    The ``--args`` and the corresponding ``--`` are removed entirely.

    The delimeter and ``--`` terminator combination can also happen multiple
    times, in which case the bodies of arguments are combined and returned in
    the order they appeared.

    For example:

    .. code-block:: python

        >> extract_argument_group(['foo',
                                   '--args', 'ping', '--',
                                   'bar',
                                   '--args', 'pong', '--',
                                   'baz',
                                   '--args', '--'], '--args')
        (['foo', 'bar', 'baz'], ['ping', 'pong'])

    Note: ``--`` cannot be used as the ``delimiting_option``.

    :param list args: list of strings which are ordered arguments.
    :param str delimiting_option: option which denotes where to split the args.
    :returns: tuple of arguments before and after the delimeter.
    :rtype: tuple
    :raises: ValueError if the delimiting_option is ``--``.
    """
    if delimiting_option == '--':
        raise ValueError("Cannot use '--' as the delimiter")
    if delimiting_option not in args:
        return args, []
    trimmed_args = args
    extracted_args = []
    # Loop through all arguments extracting groups of arguments
    while True:
        try:
            next_delimeter = trimmed_args.index(delimiting_option)
        except ValueError:
            # No delimeter's left in the arguments, stop looking
            break
        # Capture and remove args after the delimeter
        tail = trimmed_args[next_delimeter + 1:]
        trimmed_args = trimmed_args[:next_delimeter]
        # Look for a terminator, '--'
        next_terminator = None
        try:
            next_terminator = tail.index('--')
        except ValueError:
            pass
        if next_terminator is None:
            # No terminator, put all args in extracted_args and stop looking
            extracted_args.extend(tail)
            break
        else:
            # Terminator foud, put args up, but not including terminator
            # in extracted_args
            extracted_args.extend(tail[:next_terminator])
            # And put arguments after the terminator back in trimmed_args
            # then continue looking for additional delimeters
            trimmed_args.extend(tail[next_terminator + 1:])
    # Iterate through extracted args and shorted tokens with 3+ -'s only
    for i, token in enumerate(extracted_args):
        # '--' should have been removed from extracted_args in the above loop
        assert token != '--', "this shouldn't happen"
        # Skip single hyphens
        if token == '-':
            continue
        # Check for non-hyphen characters
        if [c for c in token if c != '-']:
            # contains something other than -, continue
            continue
        # Must be only hyphens with more than two, Shorted by one -
        extracted_args[i] = token[1:]
    return trimmed_args, extracted_args
