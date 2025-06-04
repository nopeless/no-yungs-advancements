# pip install PyGithub
import os
import argparse
from github import Github, GithubException

# --- Configuration ---
ORGANIZATION_NAME = "YUNG-GANG"
# The sequence of folders to find. e.g., ["resources", "data"] means find a "resources" folder
# that directly contains a "data" folder. This entire unit can be nested anywhere in the repo.
TARGET_PATH_SEGMENTS = ["resources", "data"]
TOKEN_FILE_NAME = "token"  # Name of the file to read the token from


# --- Function to get GitHub Token ---
def get_github_token():
    token = None
    try:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        token_file_path = os.path.join(script_dir, TOKEN_FILE_NAME)
        if os.path.exists(token_file_path):
            with open(token_file_path, "r") as f:
                token = f.readline().strip()
            if token:
                print(f"Using GitHub token from file: {token_file_path}")
                return token
            else:
                print(f"Token file '{token_file_path}' found but is empty.")
    except Exception as e:
        print(f"Error reading token file '{TOKEN_FILE_NAME}': {e}")

    token = os.environ.get("GITHUB_PAT")
    if token:
        print("Using GitHub token from GITHUB_PAT environment variable.")
        return token

    print("No GitHub token found in file or environment variable.")
    return None


# --- GitHub API Interaction Functions ---


def _find_strict_sequence_from_path(repo, segments, base_path):
    """
    Helper: Given a base_path, checks if segments[0]/segments[1]/...
    exists directly starting from base_path.
    Args:
        repo: The repository object.
        segments: List of subsequent folder names, e.g., ["data"] if base_path is path to "resources".
        base_path: The path from which to start checking for the sequence, e.g., "src/foo/resources".
    Returns:
        Path to the end of the sequence (e.g., "src/foo/resources/data") or None.
    """
    current_path_being_built = base_path
    for segment_name in segments:
        try:
            contents = repo.get_contents(current_path_being_built)
            found_next_segment = False
            for item in contents:
                if item.type == "dir" and item.name == segment_name:
                    current_path_being_built = (
                        item.path
                    )  # Update to the path of the found segment
                    found_next_segment = True
                    break
            if not found_next_segment:
                return None  # Required segment not found
        except GithubException as e:
            if e.status == 404:  # Path segment doesn't exist
                return None
            # print(f"  DEBUG: GitHub error in _find_strict_sequence for '{current_path_being_built}/{segment_name}': {e.status}")
            return None  # Other error (e.g. rate limit, access denied)
        except Exception as e_gen:
            # print(f"  DEBUG: Generic error in _find_strict_sequence for '{current_path_being_built}/{segment_name}': {e_gen}")
            return None
    return current_path_being_built  # Successfully found all segments in sequence


def find_target_sequence_globally(repo, segments_to_find, search_root_path=""):
    """
    Recursively searches for the first segment (segments_to_find[0]) starting from search_root_path.
    If found, it then tries to match the rest of the segments_to_find sequentially from that point.
    If segments_to_find[0] is not found directly in search_root_path's immediate children,
    it recursively searches its subdirectories for the *start* of the sequence.

    Args:
        repo: The repository object.
        segments_to_find: A list of folder names, e.g., ["resources", "data"].
        search_root_path: The current path in the repo to search within.

    Returns:
        The full path to the final segment of the sequence if found, else None.
    """
    if not segments_to_find:  # Should not be called with empty segments initially
        return None

    first_segment_name = segments_to_find[0]
    remaining_segments = segments_to_find[1:]

    try:
        contents = repo.get_contents(search_root_path)
    except GithubException as e:
        if e.status == 404:  # search_root_path itself doesn't exist or is not a dir
            return None
        # print(f"  DEBUG: GitHub error fetching contents of '{search_root_path}' in {repo.name}: {e.status}")
        # Consider logging or handling other statuses like 403 (rate limit / forbidden)
        return None
    except Exception as e_gen:
        # print(f"  DEBUG: Generic error fetching contents of '{search_root_path}' in {repo.name}: {e_gen}")
        return None

    # Stage 1: Look for first_segment_name directly in current search_root_path's children
    for item in contents:
        if item.type == "dir" and item.name == first_segment_name:
            # Found the first segment (e.g., "resources") at item.path
            # Now, try to find the remaining_segments (e.g., "data") *directly inside* it.
            if not remaining_segments:
                return (
                    item.path
                )  # Found the whole sequence (e.g., just "resources" if that was the only segment)
            else:
                # path_to_end will be the path to the end of the sequence (e.g., "path/to/resources/data")
                path_to_end_of_sequence = _find_strict_sequence_from_path(
                    repo, remaining_segments, item.path
                )
                if path_to_end_of_sequence:
                    return path_to_end_of_sequence  # Found the full sequence!

    # Stage 2: If first_segment_name was not found as a direct child (or sequence did not complete from it),
    #          recursively search for the *original, full* segments_to_find in subdirectories of search_root_path.
    for item in contents:
        if item.type == "dir":
            # Recursively search for the *entire original sequence* starting in this subdirectory item.path
            found_path_in_subdir = find_target_sequence_globally(
                repo, segments_to_find, item.path
            )
            if found_path_in_subdir:
                return found_path_in_subdir  # Propagate success upwards

    return None  # Not found in this branch of the repository structure


# --- Main Execution ---
def main():
    parser = argparse.ArgumentParser(
        description=f"Scan GitHub repositories for subfolders within a '.../{'/'.join(TARGET_PATH_SEGMENTS)}/' structure.",
        formatter_class=argparse.RawTextHelpFormatter,  # For better help text formatting
    )
    parser.add_argument(
        "repo_name",
        nargs="?",
        default=None,
        help=(
            "Optional: Specific repository name to scan.\n"
            "Examples:\n"
            "  'YUNGs-Better-Dungeons' (will be prefixed with organization name)\n"
            f"  '{ORGANIZATION_NAME}/YUNGs-Better-Dungeons' (full name)\n"
            "If not provided, all public repositories in the organization are scanned."
        ),
    )
    args = parser.parse_args()

    github_token = get_github_token()
    if github_token:
        g = Github(github_token)
        print("Using authenticated GitHub API access.")
    else:
        g = Github()
        print("Using anonymous GitHub API access. WARNING: Rate limits are very low.")
        print(
            "It's highly recommended to create a 'token' file or set GITHUB_PAT environment variable."
        )

    all_found_subfolder_names = set()
    repos_to_scan = []
    repo_count = 0

    if args.repo_name:
        target_repo_full_name = args.repo_name
        if "/" not in target_repo_full_name:
            target_repo_full_name = f"{ORGANIZATION_NAME}/{target_repo_full_name}"
        print(
            f"Attempting to fetch single specified repository: {target_repo_full_name}"
        )
        try:
            repo = g.get_repo(target_repo_full_name)
            repos_to_scan = [repo]
            repo_count = 1
            print(f"Successfully fetched {repo.full_name}.\n")
        except GithubException as e:
            print(
                f"Error fetching specified repository '{target_repo_full_name}': {e.status} {e.data}"
            )
            print("Please ensure the repository name is correct and you have access.")
            return
        except Exception as e:
            print(
                f"An unexpected error occurred fetching '{target_repo_full_name}': {e}"
            )
            return
    else:
        print(f"Fetching organization: {ORGANIZATION_NAME}")
        try:
            org = g.get_organization(ORGANIZATION_NAME)
            print(f"Fetching all repositories for {org.login}...")
            # org.get_repos() is a PaginatedList, which is iterable
            repos_to_scan = org.get_repos()
            # totalCount can be expensive for very large orgs or slow connections,
            # but useful for progress. For YUNG-GANG it's fine.
            try:
                repo_count = repos_to_scan.totalCount
                print(f"Found {repo_count} repositories. Processing...\n")
            except (
                Exception
            ):  # Some repo lists might not easily give totalCount without iteration
                print(
                    "Counting repositories... (this might take a moment for large organizations)"
                )
                # Convert to list to get count, but this fetches all repo objects upfront
                temp_repo_list = list(repos_to_scan)
                repo_count = len(temp_repo_list)
                repos_to_scan = temp_repo_list  # Use the fetched list
                print(f"Found {repo_count} repositories. Processing...\n")

        except GithubException as e:
            print(
                f"Error fetching organization or repositories for '{ORGANIZATION_NAME}': {e.status} {e.data}"
            )
            return
        except Exception as e:
            print(f"An unexpected error occurred: {e}")
            return

    processed_repo_count = 0
    for repo in repos_to_scan:
        processed_repo_count += 1
        progress_prefix = (
            f"[{processed_repo_count}/{repo_count}]" if repo_count > 0 else ""
        )
        print(f"{progress_prefix} Processing repo: {repo.full_name}")
        try:
            target_folder_full_path = find_target_sequence_globally(
                repo, TARGET_PATH_SEGMENTS
            )

            if target_folder_full_path:
                print(
                    f"  Found '{'/'.join(TARGET_PATH_SEGMENTS)}' at path: '{target_folder_full_path}'"
                )
                try:
                    data_dir_contents = repo.get_contents(target_folder_full_path)
                    found_in_this_repo = False
                    for item in data_dir_contents:
                        if item.type == "dir":
                            # print(f"    Found subfolder: {item.name}") # More verbose
                            all_found_subfolder_names.add(item.name)
                            found_in_this_repo = True
                    if not found_in_this_repo:
                        print(
                            f"    '{target_folder_full_path}' contains no subdirectories."
                        )
                except GithubException as e:
                    if e.status == 404:
                        print(
                            f"  Error: Path '{target_folder_full_path}' (found by search) seems to not exist when fetching contents."
                        )
                    else:
                        print(
                            f"  Error accessing contents of '{target_folder_full_path}' in {repo.name}: {e.status} {e.data}"
                        )
                except Exception as e_gen:
                    print(
                        f"  Unexpected error accessing contents of '{target_folder_full_path}' in {repo.name}: {e_gen}"
                    )
            # else: # Can be verbose if many repos don't have the path
            #     print(f"  Path '{'/'.join(TARGET_PATH_SEGMENTS)}' not found in {repo.name}.")

        except GithubException as e:  # Errors during the search within a repo
            print(
                f"  Skipping repo {repo.name} due to GitHub API error during search: {e.status} {e.data}"
            )
        except Exception as e_gen:
            print(
                f"  Skipping repo {repo.name} due to unexpected error during search: {e_gen}"
            )
        # print("-" * 30) # Separator

    print("\n--- Summary ---")
    if all_found_subfolder_names:
        print(
            f"Collected {len(all_found_subfolder_names)} unique subfolder names from '.../{'/'.join(TARGET_PATH_SEGMENTS)}/' paths:"
        )
        print(all_found_subfolder_names)
        for name in sorted(list(all_found_subfolder_names)):
            print(f"- {name}")
    else:
        print(
            f"No subfolders found within any '.../{'/'.join(TARGET_PATH_SEGMENTS)}/' paths."
        )

    try:
        rate_limit = g.get_rate_limit()
        print(f"\nGitHub API Rate Limit Status:")
        print(f"  Core limit: {rate_limit.core.limit}")
        print(f"  Core remaining: {rate_limit.core.remaining}")
        print(f"  Core reset time: {rate_limit.core.reset}")
    except Exception as e:
        print(f"Could not retrieve rate limit status: {e}")


if __name__ == "__main__":
    main()
