from shutil import copy2, move, Error
from send2trash import send2trash
import os
from progress_bar import progress_bar
from file_folder_getters import *
from concurrent.futures import ThreadPoolExecutor
from filecmp import cmp as compare_files
from time import time
from Filelist import Filelist
import argparse


def parse_inputs() -> tuple[bool, str, str, list[str], list[str], str, bool, bool, int, int]:
    """
    takes care of parsing the command line arguments passed to the program

    returns tuple:
    (get_file_extensions: bool,
    input_folder: str,
    output_folder: str,
    file_extensions: list[str],
    file_beginnings: list[str],
    operation: str,
    confirm_permanent_delete: bool,
    keep_folder_structure: bool,
    min_filesize: int,
    max_filesize: int)
    """
    parser = argparse.ArgumentParser(description="Does various things related to file handling and moving")
    parser.add_argument("--get_file_extensions", "-gfe", help="bool, True for getting file extensions", action="store_true", default=False)
    parser.add_argument("--input_folder", "-if", type=str, nargs="?", required=True, help="str, path to the input folder for processing")
    parser.add_argument("--output_folder", "-of", type=str, nargs="?", help="str, path to the output folder for processing")
    parser.add_argument("--file_extensions", "-fe", type=str, nargs="*", help="str, list the file extensions you want to limit processing to", default=[])
    parser.add_argument("--file_beginnings", "-fb", type=str, nargs="*", help="str, list the file beginnings you want to limit processing to", default=[])
    parser.add_argument("--min_filesize", "-minfs", type=int, nargs="?", help="int, the minimum filesize to consider for the operation", default=0)
    parser.add_argument("--max_filesize", "-maxfs", type=int, nargs="?", help="int, the maximum filesize to consider for the operation", default=2**64)
    parser.add_argument("--keep_folder_structure", "-kfs", type=bool, nargs="?", help="bool, True to keep folder structure as is, False to have no subfolders in output", choices=(True, False), default=True)
    parser.add_argument("--operation", "-op", type=str, nargs="?", choices=("C", "M", "T", "D"), help="str, file operation to perform (Copy, Move, Trash, Delete)")
    parser.add_argument("--confirm_permanent_delete", "-cpd", help="bool, required to be True to permanently delete any files", action="store_true", default=False)
    args = parser.parse_args()

    output = (args.get_file_extensions,
              args.input_folder,
              args.output_folder,
              args.file_extensions,
              args.file_beginnings,
              args.operation,
              args.confirm_permanent_delete,
              args.keep_folder_structure, 
              args.min_filesize,
              args.max_filesize)

    return output


# FIXME output_folder is not checked with assertion
def move_files(input_folder, output_folder = None, file_extensions: tuple[str, ...] = (), start_with: tuple[str, ...] = (), min_filesize: int = 0, max_filesize: int = Filelist.DEFAULT_MAX_FILESIZE, move_mode: str = "C", keep_folder_structure: bool = True, files_per_group: int = 100) -> list[tuple]:
    """
    move_mode can be either "M" for move, "C" for copy, "T" for trash, "D" for permanently delete

    output_folder should be defined for move_mode C or M, but is unused for T or D

    if file_extensions/start_with is empty tuple then all file extensions will be copied/moved

    if keep_folder_structure is False, all files in input folder and its subfolders will be dumped into the output folder,
    this only applies for move_mode in ["C", "M"]

    returns the errors
    """
    assert (move_mode in ["C", "M", "T", "D"]), "move_mode was not one of the options"
    assert (isinstance(file_extensions, tuple)), "file_extensions was not a tuple"
    assert (isinstance(start_with, tuple)), "start_with was not a tuple"
    assert (os.path.exists(input_folder)), "input_folder does not exist"
    assert (isinstance(keep_folder_structure, bool)), "keep_folder_structure was not bool"

    input_folder = os.path.abspath(input_folder) # fix slashes

    same_drive_input_output = False # in case it doesn't get defined below

    if move_mode in ["C", "M"]:
        if not os.path.exists(output_folder):
            try:
                os.makedirs(output_folder)
            except:
                assert (False), "destination folder didn't exist and couldn't be created"
        output_folder = os.path.abspath(output_folder) # fix slashes
        same_drive_input_output = (os.path.splitdrive(input_folder)[0] == os.path.splitdrive(output_folder)[0])

    # get all files
    print("finding all files in input folder...")
    filelist = Filelist(input_folder, file_extensions, start_with, min_filesize, max_filesize)
    number_of_files_total = len(filelist.get_filepaths())
    print("{} files found".format(number_of_files_total))

    input_files = filelist.get_filepaths()

    unique_folders = set() # TODO replace with filelist.get_subfolders()
    for filepath in input_files:
        folderpath = os.path.dirname(filepath)
        unique_folders.add(folderpath)

    if move_mode == "C" or (move_mode == "M" and not same_drive_input_output):
        # copy / move time is mainly based on raw MB/s throughput of drives
        rate_units = "MB"
    else:
        # basically just changing a few bytes in the filesystem per file,
        # move time is based on seek time and is constant regardless of file size
        rate_units = "files"

    number_of_files_processed = 0
    error_counts = [0 for _ in range(9999)] # I hope that I never have over 9999 possible error codes

    total_size = sum(filelist.get_filesizes())
    total_processed_size = 0

    if move_mode == "C":
        print("Copying Files from \"{}\" to \"{}\"".format(input_folder, output_folder))
    elif move_mode == "M":
        print("Moving Files from \"{}\" to \"{}\"".format(input_folder, output_folder))
    elif move_mode == "T":
        print("Trashing Files from \"{}\"".format(input_folder))
    elif move_mode == "D":
        print("PERMANENTLY DELETING Files from \"{}\"".format(input_folder))

    print("") # newline since first progress_bar() will \r

    grouped_filepaths = [input_files[i:i+files_per_group] if i+files_per_group < len(input_files) else input_files[i:] for i in range(0, len(input_files), files_per_group)]

    threads = list()

    progress_bar_object = progress_bar(100, rate_units="Threads")
    progress = 0

    print("creating threads...")
    with ThreadPoolExecutor() as executor:
        for filepaths in grouped_filepaths:
            thread = executor.submit(__move_files_unit_processor, filepaths, input_folder, output_folder, unique_folders, move_mode, keep_folder_structure)
            threads.append(thread)

        print("waiting for threads to return...")
        all_threads_done = False
        last_done_count = 0
        while not all_threads_done:
            done_count = 0
            for thread in threads:
                done_count += thread.done()
            all_threads_done = (done_count == len(threads))
            if done_count == 0:
                continue
            if last_done_count != done_count:
                last_done_count = done_count
                progress_bar_object.print_progress_bar(done_count / len(threads), done_count)
            else:
                sleep(min((progress_bar_object.get_ETA(done_count / len(threads))/100, 1)))

        print("") # to add a newline after the end of the progress bar

        progress_bar_object = progress_bar(100, rate_units=rate_units)

        print("processing outputs...")
        for thread in threads:
            (new_error_counts, new_number_of_files_processed, number_of_failed_files, new_total_processed_size, failed_files_size) = thread.result()
            number_of_files_total -= number_of_failed_files
            total_size -= failed_files_size
            for i in range(len(error_counts)):
                error_counts[i] += new_error_counts[i]
            number_of_files_processed += new_number_of_files_processed
            total_processed_size += new_total_processed_size

            # update progress
            if move_mode == "C" or (move_mode == "M" and not same_drive_input_output):
                # copy / move time is mainly based on raw MB/s throughput of drives
                try:
                    progress = total_processed_size / total_size
                except ZeroDivisionError:
                    progress = 1 / 2**32
                rate_progress = total_processed_size / (10**6)
            else:
                # basically just changing a few bytes in the filesystem per file,
                # move time is based on seek time and is constant regardless of file size
                progress = number_of_files_processed / number_of_files_total
                rate_progress = number_of_files_processed

            progress_bar_object.print_progress_bar(progress, rate_progress)
    
    print("") # to add a newline after the end of the progress bar

    # process error_counts to only return what errors did happen:
    error_return: list[tuple] = list()
    for error_number in range(len(error_counts)):
        if error_counts[error_number] > 0:
            error_return.append((error_number, error_counts[error_number]))

    return error_return


def __move_files_unit_processor(filepaths: tuple[str, ...], input_folder, output_folder, unique_folders: set[str], move_mode: str, keep_folder_structure: bool):
    """
    multithreaded unit processor for move files
    do not use on its own
    """
    total_processed_size = 0
    error_counts = [0 for _ in range(9999)] # I hope that I never have over 9999 possible error codes
    number_of_files_processed = 0
    number_of_failed_files = 0
    failed_files_size = 0

    for filepath in filepaths:
        success = (-1, "") # reset to assume no problems happen
        current_filesize = os.stat(filepath).st_size # bytes filesize
        total_processed_size += current_filesize

        if keep_folder_structure and move_mode in ("C", "M"):
            relative_output_path = os.path.dirname(filepath).removeprefix(input_folder) # the subfolder structure inside of input_folder
            output_folder_path = os.path.abspath(output_folder + "/" + relative_output_path) # copy that subfolder structure to output
        else:
            output_folder_path = output_folder

        output_file_exists = True # assume this to get rid of unbound variable warning
        if move_mode in ("C", "M"):
            output_folder_exists = os.path.exists(output_folder_path)
            if not output_folder_exists:
                try:
                    os.makedirs(output_folder_path)
                except:
                    assert (False), "destination folder didn't exist and couldn't be created"
            output_file_exists: bool = os.path.exists(os.path.abspath(output_folder_path+"/"+os.path.split(filepath)[1]))

        try:
            if move_mode == "C":
                if not output_file_exists:
                    copy2(filepath, output_folder_path)
                else:
                    # if file already exists, check if it's the same file, etc
                    success = move_file_error(filepath, output_folder_path, move_mode)
                    error_counts[success[0]] += 1
            elif move_mode == "M":
                if not output_file_exists:
                    move(filepath, output_folder_path)
                else:
                    # if file already exists, you can trash this copy
                    success = move_file_error(filepath, output_folder_path, move_mode)
                    error_counts[success[0]] += 1
            elif move_mode == "T":
                send2trash(filepath)
            elif move_mode == "D":
                os.remove(filepath)

            if move_mode in ("T", "D", "M"):
                folderpath = os.path.dirname(filepath)
                clean_subfolders(folderpath, unique_folders)

        except Error: # this shouldn't happen, and the line below will not be able to fix it
            success = move_file_error(filepath, output_folder_path, move_mode)
            error_counts[success[0]] += 1
        except FileNotFoundError: # file was deleted, renamed or moved before it could be processed
            error_counts[6] += 1
        except: # unknown error
            error_counts[5] += 1
        number_of_files_processed += 1

        # if there was a failure, update the progress accordingly
        if success[0] in (0, 1, 3, 5):
            number_of_files_processed -= 1
            number_of_failed_files += 1
            total_processed_size -= current_filesize
            failed_files_size += current_filesize

    return (error_counts, number_of_files_processed, number_of_failed_files, total_processed_size, failed_files_size)


def move_file_error(filepath: str, destination_folder, move_mode: str = "C", max_retries = 100) -> tuple[int, str]:
    """
    deals with errors in copying a file.
    it's probably just that the destination already has the filename

    returns a pair of error number and accompanying string to explain the error
    """
    assert (move_mode in ("C", "M")), "move_mode invalid for error handling"
    assert (os.path.exists(filepath)), "filepath does not exist"

    filename = os.path.split(filepath)[1]

    errors: list[tuple[int, str]] = [(0, "File already existed and nothing was changed"),
                                     (1, "File already existed and extra copy was trashed"),
                                     (2, "File was renamed and copied/moved"),
                                     (3, "Couldn't find a filename that worked, gave up"),
                                     (4, "File was renamed to resolve conflict"),
                                     (5, "Error couldn't be resolved"),
                                     (6, "File could not be found")]

    if not os.path.exists(destination_folder):
        try:
            os.makedirs(destination_folder)
        except:
            assert (False), "destination folder didn't exist and couldn't be created"

    error_is_filename_conflict = os.path.exists(os.path.abspath(destination_folder+"/"+filename))

    destination_exists = True # assume this to get rid of unbound variable warning
    new_filename = "" # assume this to get rid of unbound variable warning
    if error_is_filename_conflict:
        # check if files are the same
        files_are_identical = compare_files(filepath, os.path.abspath(destination_folder+"/"+filename), shallow = False)

        if files_are_identical:
            # assumed to be the same file, original can be safely moved to trash
            if move_mode == "M":
                send2trash(filepath)
                return errors[1]
            # if move mode was copy then do nothing
            return errors[0]

        for retry_count in range(max_retries):
            # retry up to 100 times to copy file with new filename
            new_filename_parts = filename.split(".")
            new_filename: str = ".".join(new_filename_parts[:-1]) + " ({})".format(retry_count) + "." + new_filename_parts[-1]
            destination_exists: bool = os.path.exists(os.path.abspath(destination_folder+"/"+new_filename))

            if not destination_exists:
                break # new_filename can be used

            files_are_identical = compare_files(filepath, os.path.abspath(destination_folder+"/"+filename), shallow = False)

            if files_are_identical:
                if move_mode == "M":
                    send2trash(filepath)
                    return errors[1]
                # if move mode was copy then do nothing
                return errors[0]
        
        if destination_exists and not files_are_identical:
            # this means we went through all the retry attempts
            # and couldn't find somewhere to put source file,
            # so we gave up
            return errors[3]

        # this code will assume that if you have a filename conflict where both files have:
        # - same size in bytes
        # that these are the same file. It's unlikely that they aren't, that, well, I'm not going to run a checksum
        # I previously had date checks but they were unreliable and resulted in duplicated files

        # if we get here, then the destination did not contain a copy of this file,
        # so we use new_filename to copy/move the source file
        try:
            if move_mode == "C":
                copy2(filepath, os.path.abspath(destination_folder+"/"+new_filename)) # this is guaranteed not to overwrite a file
            else:
                move(filepath, os.path.abspath(destination_folder+"/"+new_filename)) # this is guaranteed not to overwrite a file
            return errors[4] # error was resolved
        except Error:
            # couldn't resolve the issue for some reason
            return errors[5]

    else: # if error was not filename conflict
        # for now I don't know what else the error could be
        return errors[5] # error was not resolved


def main() -> None:
    start_time = time()
    (get_file_extensions_or_run_program, input_folder, output_folder, file_extensions, file_starts, move_mode, permanent_delete_confirmed, keep_folder_structure, min_filesize, max_filesize) = parse_inputs()
    assert (os.path.exists(input_folder)), "input folder does not exist"

    if get_file_extensions_or_run_program: # True means get file extensions
        filelist = Filelist(input_folder)
        [print(extension, end=" ") for extension in filelist.get_file_extensions()]
        print("") # add a newline after the list

    else:
        assert (move_mode in ("C", "M", "T", "D")), "operation type invalid or not given"
        assert (move_mode != "D" or permanent_delete_confirmed), "permanent deletion must be confirmed with --confirm_permanent_delete or -cpd"
        file_extensions = tuple(file_extensions)
        file_starts = tuple(file_starts)

        print("\n\nerrors: " + str(move_files(input_folder, output_folder, file_extensions, file_starts, min_filesize, max_filesize, move_mode, keep_folder_structure)))

    print("{} seconds to run".format(time() - start_time))
    return None


if __name__ == "__main__":
    main()
