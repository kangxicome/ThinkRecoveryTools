# -*- coding: utf-8 -*-
#
# Filename: ThinkRecoveryUSBMakerAdv.py
# Description: A command-line tool to create Lenovo Recovery USB drives from .RMF and downloaded recovery files.
#
# Author:       Kenzo Love Yuki
# Date:         November 30, 2025
# Version:      2.0
#
# Usage:
#   1. Ensure '7z.exe' and 'aodbuild.exe' are accessible (e.g., in PATH or script directory).
#   2. Run: python ThinkRecoveryUSBMakerAdv.py
#
# Dependencies:
#   pip install windows-curses

import sys
import os
import shutil
import subprocess
import xml.etree.ElementTree as ET
import threading
import queue
import curses
from datetime import datetime

# --- Global Constants ---

IMZ_PW_CHARS = "k`gybs0vampjd" # Magic Code, from Lenovo Think Community, I don't know what it is :>

# Application Metadata for Title Bar
APP_TITLE = "Think Recovery USB Maker Advanced"
APP_AUTHOR = "Kenzo Love Yuki"
APP_VERSION = "2.0"

# Default Paths
DEFAULT_DL = r"c:\ProgramData\Lenovo\USBRecoveryCreator\Downloads"
DEFAULT_PATCH = r"c:\ProgramData\Lenovo\USBRecoveryCreator\Patch"
DEFAULT_TARGET = os.path.join(os.getcwd(), "USB")

# Input field labels and IDs
INPUT_FIELDS = [
    ("1. .RMF File Path:", "rmf_path", ""),
    ("2. Recovery Source Directory:", "source_dir", DEFAULT_DL),
    ("3. Patch Source Directory (Optional):", "patch_dir", DEFAULT_PATCH),
    ("4. Target USB Directory:", "target_dir", DEFAULT_TARGET)
]
NUM_INPUTS = len(INPUT_FIELDS)
ACTION_DONE_TOKEN = "PROCESS_DONE" # Unique token to signal thread completion

# --- Core Logic / Helper Functions ---

def encrypt_imz_password(clear_password):
    """
    Encrypts the Lenovo IMZ password based on the 'key' attribute in the RMF file.
    """
    if not clear_password:
        return ""
    
    ciphered_chars = []
    for i in range(len(clear_password)):
        clear_char = clear_password[i]
        char_index = ord(clear_char) % 13
        pwchars_char = IMZ_PW_CHARS[char_index]
        ciphered_ordinal = ord(pwchars_char) - (i % 3) + 2
        ciphered_char = chr(ciphered_ordinal)
        ciphered_chars.append(ciphered_char)

    return "".join(ciphered_chars)

def post_process_files(recovery_target, patch_source, script_dir, log_queue):
    """Handles rename, EFI overwrite, and AOD rebuilding."""
    
    def log(action, filename, path, result):
        log_queue.put({"action": action, "filename": filename, "path": path, "result": result})

    copied_cri_name = None
        
    # 1. Rename MFG -> mfg
    try:
        old_path = os.path.join(recovery_target, 'MFG')
        new_path = os.path.join(recovery_target, 'mfg')
        if os.path.isdir(old_path):
            os.rename(old_path, new_path)
            log("MODIFY", "Folder MFG", "root", "Renamed to 'mfg'")
    except Exception as e:
        log("MODIFY", "Folder MFG", "", f"Error: {e}")

    if patch_source and os.path.exists(patch_source):
        # 2. Overwrite EFI
        try:
            source_efi = os.path.join(patch_source, 'EFI')
            target_efi = os.path.join(recovery_target, 'EFI')
            if os.path.isdir(source_efi):
                if os.path.exists(target_efi):
                    shutil.rmtree(target_efi)
                shutil.copytree(source_efi, target_efi)
                log("COPY", "EFI Folder", "root", "Overwritten from Patch")
        except Exception as e:
            log("COPY", "EFI Folder", "", f"Error: {e}")

        # 3. Handle CRI and IMZ
        try:
            target_rec_dir = os.path.join(recovery_target, 'RECOVERY')
            os.makedirs(target_rec_dir, exist_ok=True)
            
            patch_files = os.listdir(patch_source)
            for filename in patch_files:
                if filename.lower().endswith('.cri'):
                    cri_path = os.path.join(patch_source, filename)
                    
                    # Basic check to filter out ARM based CRI (simple text search)
                    is_arm = False
                    try:
                        with open(cri_path, 'r', encoding='utf-8', errors='ignore') as f:
                            content = f.read().upper()
                        if "ARM" in content and ("OS" in content or "PLATFORM" in content):
                            is_arm = True
                    except: pass
                    
                    if is_arm:
                        log("SKIP", filename, "", "ARM Architecture detected")
                        continue

                    # Find corresponding IMZ
                    base_name = os.path.splitext(filename)[0]
                    imz_filename = base_name + '.IMZ'
                    imz_path = os.path.join(patch_source, imz_filename)

                    if os.path.exists(imz_path):
                        shutil.copy2(cri_path, target_rec_dir)
                        shutil.copy2(imz_path, target_rec_dir)
                        copied_cri_name = filename
                        log("COPY", f"{filename} & .IMZ", "RECOVERY", "Copied from Patch")
                        break # Only process the first valid pair
        except Exception as e:
            log("COPY", "CRI/IMZ", "", f"Error: {e}")

    # 4. AOD Processing
    if copied_cri_name:
        target_rec_dir = os.path.join(recovery_target, 'RECOVERY')
        aod_dat = os.path.join(target_rec_dir, 'AOD.DAT')
        aod_org = os.path.join(target_rec_dir, 'AOD.ORG')
        aod_stat = os.path.join(target_rec_dir, 'aodstat.dat')

        if os.path.exists(aod_dat):
            try:
                # Rename DAT -> ORG
                os.rename(aod_dat, aod_org)
                
                # Run aodbuild
                aodbuild_exe = os.path.join(script_dir, 'aodbuild.exe')
                if not os.path.exists(aodbuild_exe):
                    log("ERROR", "aodbuild.exe", "", "Tool missing in script dir")
                    return

                cmd = [aodbuild_exe, f'/F:{copied_cri_name}', '/P:AOD.ORG']
                proc = subprocess.run(cmd, cwd=target_rec_dir, capture_output=True, text=True, encoding='utf-8')
                
                if proc.returncode == 0:
                    log("EXEC", "aodbuild.exe", "RECOVERY", "Success")
                else:
                    log("EXEC", "aodbuild.exe", "", f"Fail: {proc.stderr}")

                # Rename aodstat.dat -> AOD.DAT
                if os.path.exists(aod_stat):
                    os.rename(aod_stat, aod_dat)
                    
                    # Splice Header
                    with open(aod_org, 'r', encoding='utf-8') as f_org:
                        header_lines = [next(f_org) for _ in range(4)]
                    with open(aod_dat, 'r', encoding='utf-8') as f_dat:
                        content_lines = f_dat.readlines()
                    
                    content_lines[:4] = header_lines
                    final_lines = [line for line in content_lines if line.strip()]
                    
                    with open(aod_dat, 'w', encoding='utf-8') as f_out:
                        f_out.writelines(final_lines)
                        
                    log("MODIFY", "AOD.DAT", "RECOVERY", "Header updated & Cleaned")
                else:
                    log("ERROR", "aodstat.dat", "", "Not generated by aodbuild")

            except Exception as e:
                log("ERROR", "AOD Processing", "", str(e))
    
    log_queue.put({"action": "STATUS", "filename": "", "path": "", "result": "Post-processing complete."})


def parse_rmf_for_dialog(rmf_path, log_queue):
    """Parses RMF for basic info and extracts VALUES.TXT content."""
    
    def log(action, filename, path, result):
        log_queue.put({"action": action, "filename": filename, "path": path, "result": result})
        
    try:
        if not os.path.exists(rmf_path):
            log("ERROR", os.path.basename(rmf_path), "", "RMF file not found.")
            return None, None
            
        tree = ET.parse(rmf_path)
        root = tree.getroot()
        recovery_node = root.find('recovery')
        if recovery_node is None:
            log("ERROR", os.path.basename(rmf_path), "", "Node 'recovery' not found in RMF.")
            return None, None
            
        manualfiles_node = recovery_node.find('manualfiles')
        if manualfiles_node is None:
            return root, None # No manual files, proceed without dialog

        values_txt_content = None
        for file_node in manualfiles_node.findall('file'):
            if file_node.get('name', '').upper() == 'VALUES.TXT':
                fcontent_node = file_node.find('fcontent')
                if fcontent_node is not None and fcontent_node.text:
                    # Clean up the text content for display
                    # Format: 0) Name: 	ThinkPad X1 Nano Gen 1\n1) CD#: 	1 of 1...
                    content = fcontent_node.text.strip()
                    # Replace tabs and ensure consistent spacing for display
                    content = content.replace('\t', ' ')
                    
                    # Standardize format for display in curses (pad field names)
                    # The original format has key: value, we just want to preserve the lines
                    values_txt_content = []
                    for line in content.split('\n'):
                        if line.strip():
                            # Reformat using consistent padding, assuming standard format
                            try:
                                key_part, val_part = line.split(':', 1)
                                # Try to match the original padding requested by the user
                                formatted_line = f"{key_part.strip():<8}:\t{val_part.strip()}"
                                values_txt_content.append(formatted_line)
                            except ValueError:
                                values_txt_content.append(line.strip())
                    
                    values_txt_content = '\n'.join(values_txt_content)
                    break
        
        return root, values_txt_content
        
    except Exception as e:
        log("ERROR", os.path.basename(rmf_path), "", f"XML Parse Fail: {str(e)}")
        return None, None


def run_recovery_process(rmf_root, source_dir, patch_dir, target_dir, log_queue):
    """The main logic running in a background thread. Uses pre-parsed RMF root."""
    script_dir = os.path.dirname(os.path.abspath(sys.argv[0]))

    def log(action, filename, path, result):
        log_queue.put({"action": action, "filename": filename, "path": path, "result": result})
        
    try:
        # 1. Create Target Directory
        os.makedirs(target_dir, exist_ok=True)
        log("INIT", "Target Dir", target_dir, "Created/Verified")

        # Use the pre-parsed root
        recovery_node = rmf_root.find('recovery')

        # 2. Handle 'manualfiles' (CREATE)
        manualfiles_node = recovery_node.find('manualfiles')
        if manualfiles_node is not None:
            for file_node in manualfiles_node.findall('file'):
                filename = file_node.get('name')
                copypath_rel = file_node.get('copypath', '').strip('/\\')
                fcontent_node = file_node.find('fcontent')
                
                if filename and fcontent_node is not None and fcontent_node.text:
                    full_target_path = os.path.join(target_dir, copypath_rel, filename)
                    os.makedirs(os.path.dirname(full_target_path), exist_ok=True)
                    try:
                        # Skip logging of VALUES.TXT creation if it was just verified
                        log_msg = "Success"
                        if filename.upper() == 'VALUES.TXT':
                            log_msg = "Content Verified (Written)"
                            
                        with open(full_target_path, 'w', encoding='utf-8') as f:
                            f.write(fcontent_node.text.strip())
                        
                        log("CREATE", filename, copypath_rel, log_msg)

                    except Exception as e:
                        log("CREATE", filename, copypath_rel, f"Error: {e}")

        # 3. Handle 'files' (COPY / UNPACK)
        files_node = recovery_node.find('files')
        if files_node is not None:
            all_files = files_node.findall('file')
            for file_node in all_files:
                source_file = file_node.get('source')
                if not source_file: continue

                copy_action = file_node.get('copy')
                copypath_rel = file_node.get('copypath', '').strip('/\\')
                key = file_node.get('key')
                name = file_node.get('name')
                
                final_name = name if name else os.path.basename(source_file)
                source_full_path = os.path.join(source_dir, source_file)
                target_subdir = os.path.join(target_dir, copypath_rel)

                os.makedirs(target_subdir, exist_ok=True)

                if not os.path.exists(source_full_path):
                    log("MISSING", source_file, "", "Source not found")
                    continue

                if copy_action == '1':
                    # Copy
                    target_full_path = os.path.join(target_subdir, final_name)
                    try:
                        shutil.copy2(source_full_path, target_full_path)
                        log("COPY", source_file, copypath_rel, "Success")
                    except Exception as e:
                        log("COPY", source_file, copypath_rel, f"Error: {e}")

                elif copy_action == '0':
                    # Unpack (7z)
                    password = encrypt_imz_password(key)
                    cmd = ['7z', 'x', source_full_path, f'-o{target_subdir}', '-y']
                    if password:
                        cmd.append(f'-p{password}')
                    
                    try:
                        proc = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8')
                        if proc.returncode == 0:
                            log("UNPACK", source_file, copypath_rel, "Success")
                        else:
                            error_output = (proc.stderr or proc.stdout).strip().split('\n')[-1]
                            log("UNPACK", source_file, copypath_rel, f"Fail ({error_output})")
                    except FileNotFoundError:
                        log("UNPACK", "7z.exe", "", "Not Found in Path")
                    except Exception as e:
                        log("UNPACK", source_file, "", f"Exception: {e}")

        # 4. Post-Processing
        post_process_files(target_dir, patch_dir, script_dir, log_queue)

        log("STATUS", "", "", "Recovery Creation Completed!")

    except Exception as e:
         log("FATAL", "Main Loop", "", str(e))
    finally:
        log_queue.put({"action": ACTION_DONE_TOKEN, "filename": "", "path": "", "result": "Finished"})


# --- Curses UI Functions ---

def draw_title_bar(stdscr, max_width):
    """Draws the fixed title bar at the top."""
    title_text = f" {APP_TITLE} | Written By: {APP_AUTHOR} | Version: {APP_VERSION} "
    stdscr.addstr(0, 0, title_text.ljust(max_width)[:max_width], curses.A_REVERSE | curses.A_BOLD)


def show_modal_dialog(stdscr, title, message, prompt="Proceed?", default_yes=True):
    """
    Displays a blocking modal dialog with a message and Yes/No prompt.
    Returns True for Yes, False for No, None if exited/error.
    """
    
    H, W = stdscr.getmaxyx()
    message_lines = message.split('\n')
    
    # Calculate window dimensions based on content
    max_line_len = max(len(line) for line in message_lines) if message_lines else 0
    # Add buffer for padding and borders
    win_w = min(W - 4, max_line_len + 8) 
    win_h = len(message_lines) + 8 
    
    # Calculate center position
    start_y = (H - win_h) // 2
    start_x = (W - win_w) // 2

    # Create the modal window
    modal_win = curses.newwin(win_h, win_w, start_y, start_x)
    modal_win.keypad(True)
    modal_win.nodelay(False) # Block until key is pressed

    # Button labels and state
    buttons = ["Yes (Y/Enter)", "No (N)"]
    focus_index = 0 # Default Yes

    # Draw loop for the modal
    while True:
        modal_win.erase()
        modal_win.border(0)
        
        # Title
        modal_win.addstr(0, 2, f" {title} ", curses.A_BOLD)

        # Message content
        for i, line in enumerate(message_lines):
            try:
                # Truncate lines that are too long for the modal window
                modal_win.addstr(i + 2, 2, line[:win_w - 4])
            except curses.error:
                pass

        # Prompt
        prompt_y = len(message_lines) + 3
        modal_win.addstr(prompt_y, 2, prompt, curses.A_BOLD)
        
        # Buttons
        # Center the buttons
        btn_width = sum(len(b) + 4 for b in buttons) # Length of buttons + spaces/brackets
        btn_start_x = (win_w - btn_width) // 2 + 2 
        current_x = btn_start_x
        
        for i, btn_text in enumerate(buttons):
            attr = curses.A_NORMAL
            if i == focus_index:
                attr = curses.A_REVERSE | curses.A_BOLD
            
            modal_win.addstr(prompt_y + 2, current_x, f"[{btn_text}]", attr)
            current_x += len(btn_text) + 4
            
        modal_win.refresh()

        # Input handling
        c = modal_win.getch()
        
        if c in (ord('y'), ord('Y')):
            return True # Quick Yes

        elif c in (ord('n'), ord('N')):
            return False # Quick No
            
        elif c == curses.KEY_LEFT:
            focus_index = max(0, focus_index - 1)
        elif c == curses.KEY_RIGHT:
            focus_index = min(1, focus_index + 1)
        elif c == curses.KEY_ENTER or c == 10 or c == 13:
            return focus_index == 0 # Return current focus (0=Yes, 1=No)
            
        elif c in (ord('q'), ord('Q')):
            return None # Exit application signal (handled by caller)


def draw_input_panel(stdscr, input_values, focus_index, max_width):
    """Draws all input fields and labels."""
    # Note: input_win now starts at Y=1 due to the Title Bar
    
    # Calculate padding for inputs
    label_width = max(len(label) for label, _, _ in INPUT_FIELDS)
    input_start_col = label_width + 4
    input_width = max_width - input_start_col - 2
    
    # Hide cursor initially
    curses.curs_set(0)

    for i, (label, key, _) in enumerate(INPUT_FIELDS):
        row = i * 2 + 1
        
        # Draw label
        stdscr.addstr(row, 2, label)
        
        value = input_values.get(key, "")
        display_value = value
        attr = curses.A_NORMAL
        
        # Draw input box
        if i == focus_index:
            attr = curses.A_REVERSE | curses.A_BOLD
            curses.curs_set(1) # Show cursor when in an input field
            cursor_pos = len(value)
            
            # Logic to visually scroll the input field if the path is too long
            display_start = max(0, cursor_pos - input_width + 1)
            display_value = value[display_start:display_start + input_width]
            
            # Move cursor to the actual display position
            stdscr.move(row, input_start_col + (cursor_pos - display_start))
        else:
            # If not focused, display the start of the path (or the whole path if short enough)
            display_value = value[:input_width]
            
        # Draw the text content
        # Note: The input panel window is no longer used, drawing directly to stdscr starting at Y=1
        # The coordinates are relative to the top of the input area (which is Y=1)
        
        # Redraw borders for the configuration area (Y=1 to Y=input_h-1)
        # Note: The main loop handles the window setup now, using the main screen (stdscr) for the input area

        try:
            # We are drawing directly to the sub-window, which is why we need to use its coordinates
            # input_win drawing is managed inside main() now.
            pass
        except curses.error:
            pass
        
    # Redrawing inputs in the input_win, which starts at Y=1 relative to stdscr.
    
    # Redrawing input panel border and title using the passed stdscr (which is input_win's parent in concept)
    # The actual window structure is a bit complex, let's stick to using the actual input_win for drawing.
    # The draw_input_panel is called with `input_win` in main, so it should draw correctly relative to that window's origin (0,0).
    stdscr.erase()
    stdscr.border(0)
    stdscr.addstr(0, 2, " Configuration ", curses.A_BOLD)

    for i, (label, key, _) in enumerate(INPUT_FIELDS):
        row = i * 2 + 1
        
        # Draw label
        stdscr.addstr(row, 2, label)
        
        value = input_values.get(key, "")
        display_value = value
        attr = curses.A_NORMAL
        
        if i == focus_index:
            attr = curses.A_REVERSE | curses.A_BOLD
            curses.curs_set(1) 
            cursor_pos = len(value)
            display_start = max(0, cursor_pos - input_width + 1)
            display_value = value[display_start:display_start + input_width]
            stdscr.move(row, input_start_col + (cursor_pos - display_start))
        else:
            display_value = value[:input_width]
            
        stdscr.addstr(row, input_start_col - 1, "[", curses.A_BOLD)
        stdscr.addstr(row, input_start_col, display_value.ljust(input_width)[:input_width], attr)
        stdscr.addstr(row, input_start_col + input_width, "]", curses.A_BOLD)
    
    # Draw button
    btn_row = NUM_INPUTS * 2 + 2
    btn_text = " START RECOVERY CREATION (ENTER) "
    btn_start_col = (max_width - len(btn_text)) // 2
    
    btn_attr = curses.color_pair(1) | curses.A_BOLD
    if focus_index == NUM_INPUTS:
        btn_attr |= curses.A_REVERSE
        curses.curs_set(0)
        
    stdscr.addstr(btn_row, btn_start_col, btn_text, btn_attr)
    stdscr.refresh()


def draw_log_panel(log_win, log_lines, log_scroll_offset):
    """Draws the log table in a separate window with scroll indicator."""
    log_win.erase()
    log_win.border(0)
    
    log_win.addstr(0, 2, " Operation Log ", curses.A_BOLD)
    
    win_h, win_w = log_win.getmaxyx()
    content_h = win_h - 3 

    header = "{:<8} {:<25} {:<25} {:<20}".format("Action", "Filename", "Target Path", "Result")
    log_win.addstr(1, 1, header.ljust(win_w - 2)[:win_w - 2], curses.A_UNDERLINE)

    
    start_line = log_scroll_offset
    end_line = min(start_line + content_h, len(log_lines))
    
    for i, line in enumerate(log_lines[start_line:end_line]):
        try:
            log_win.addstr(i + 2, 1, line.ljust(win_w - 2)[:win_w - 2])
        except curses.error:
            pass
            
    if len(log_lines) > content_h:
        max_scroll = len(log_lines) - content_h
        scroll_ratio = log_scroll_offset / max_scroll
        bar_len = win_w - 6 
        bar_pos = int(scroll_ratio * bar_len)
        
        bar_str = '[' + '-' * bar_len + ']'
        log_win.addstr(win_h - 1, 1, bar_str, curses.A_DIM)
        
        thumb_str = '#'
        log_win.addstr(win_h - 1, 2 + bar_pos, thumb_str, curses.A_REVERSE)

    log_win.refresh()

def format_log(item):
    """Formats a log dict into a single line string."""
    action = item.get("action", "")
    filename = item.get("filename", "")
    path = item.get("path", "")
    result = item.get("result", "")
    
    log_line = "{:<8} {:<25} {:<25} {:<20}".format(
        action, 
        filename[:25], 
        path[:25], 
        result
    )
    return log_line

def main(stdscr):
    """Main curses application loop."""
    
    # 1. Initialize Curses
    curses.curs_set(0) 
    stdscr.timeout(50) 
    
    if curses.has_colors():
        curses.start_color()
        curses.init_pair(1, curses.COLOR_BLACK, curses.COLOR_GREEN) # Button
        curses.init_pair(2, curses.COLOR_WHITE, curses.COLOR_RED)   # Error
        curses.init_pair(3, curses.COLOR_BLACK, curses.COLOR_YELLOW)# Warning/Skip
        curses.init_pair(4, curses.COLOR_WHITE, curses.COLOR_BLACK) # Normal/Header

    # 2. Setup Windows (Initial sizing)
    H, W = stdscr.getmaxyx()
    title_h = 1 # New title bar height
    input_h = NUM_INPUTS * 2 + 4
    
    # Input window starts at Y=1 (below the title bar)
    input_win = curses.newwin(input_h, W, title_h, 0)
    input_win.keypad(True)

    log_win_h = H - input_h - title_h
    log_win = curses.newwin(log_win_h, W, input_h + title_h, 0)
    
    # 3. State Management
    focus_index = 0 
    is_running = False
    
    input_values = {key: default for _, key, default in INPUT_FIELDS}
    
    log_lines = []
    log_scroll_offset = 0 
    user_scrolled = False 
    log_queue = queue.Queue() 

    # 4. Main Loop
    while True:
        try:
            # A. Draw UI
            H, W = stdscr.getmaxyx()
            
            # 0. Draw Title Bar on stdscr
            draw_title_bar(stdscr, W)
            
            # 1. Resize and reposition windows
            input_win.resize(input_h, W)
            input_win.mvwin(title_h, 0) # Move below title bar
            
            log_win_h = H - input_h - title_h
            log_win.resize(log_win_h, W)
            log_win.mvwin(input_h + title_h, 0) # Move below input window
            log_content_h = log_win_h - 3
            
            # 2. Draw content
            draw_input_panel(input_win, input_values, focus_index, W)
            draw_log_panel(log_win, log_lines, log_scroll_offset)
            stdscr.refresh()
            
            # B. Process Log Queue (Logging and Auto-scroll)
            max_scroll = max(0, len(log_lines) - log_content_h)
            
            while not log_queue.empty():
                log_item = log_queue.get_nowait()
                
                if log_item["action"] == ACTION_DONE_TOKEN:
                    is_running = False
                    log_lines.append(format_log({"action": "STATUS", "filename": "Process", "path": "Execution", "result": "Finished."}))
                else:
                    log_lines.append(format_log(log_item))
                
                if not user_scrolled:
                    log_scroll_offset = max(0, len(log_lines) - log_content_h)
                
                log_queue.task_done()
                max_scroll = max(0, len(log_lines) - log_content_h)

            
            # C. Handle Input
            # Get input from stdscr to catch keys outside of sub-windows
            c = stdscr.getch()
            if c == -1: 
                continue

            if c in (ord('q'), ord('Q')): 
                break
            
            if c == curses.KEY_RESIZE:
                stdscr.clear()
                continue
            
            # --- Scrolling Logic (If running or manually scrolled) ---
            if is_running:
                if c == curses.KEY_UP:
                    log_scroll_offset = max(0, log_scroll_offset - 1)
                    user_scrolled = True
                elif c == curses.KEY_DOWN:
                    log_scroll_offset = min(max_scroll, log_scroll_offset + 1)
                    if log_scroll_offset == max_scroll:
                        user_scrolled = False
                continue
                
            # --- Input Navigation (Uses Arrow Keys, Tab, Enter) ---
            if c == curses.KEY_UP:
                focus_index = max(0, focus_index - 1)

            elif c == curses.KEY_DOWN or c == ord('\t'):
                focus_index = min(NUM_INPUTS, focus_index + 1)

            elif c == curses.KEY_ENTER or c == 10 or c == 13: # Enter/Return
                if focus_index == NUM_INPUTS:
                    # START Button Pressed
                    rmf = input_values.get('rmf_path', '').strip()
                    src = input_values.get('source_dir', '').strip()
                    patch = input_values.get('patch_dir', '').strip()
                    target = input_values.get('target_dir', '').strip()
                    
                    if not rmf or not os.path.exists(rmf) or not src or not os.path.exists(src):
                        log_lines = [format_log({"action": "ERROR", "filename": "Validation", "path": "", "result": "RMF/Source path missing or invalid."})]
                        log_scroll_offset = 0
                        user_scrolled = False
                        continue
                        
                    # 1. Clear log and set status
                    log_lines = []
                    log_scroll_offset = 0
                    user_scrolled = False
                    
                    log_lines.append(format_log({"action": "STATUS", "filename": "RMF", "path": "Parsing", "result": "Checking for VALUES.TXT..."}))
                    # Force redraw for immediate feedback using the log window
                    draw_log_panel(log_win, log_lines, log_scroll_offset) 

                    # 2. Parse RMF in main thread
                    rmf_root, values_txt_content = parse_rmf_for_dialog(rmf, log_queue)
                    
                    if rmf_root is None:
                        continue 

                    # 3. Handle Dialog if VALUES.TXT is found
                    proceed = True
                    if values_txt_content:
                        log_lines.append(format_log({"action": "STATUS", "filename": "Dialog", "path": "VALUES.TXT", "result": "Found. Awaiting confirmation."}))
                        
                        # --- MODAL DIALOG CALL ---
                        modal_result = show_modal_dialog(
                            stdscr, # Pass the main screen for the modal to draw over everything
                            "RMF Metadata Verification", 
                            values_txt_content, 
                            prompt="Proceed? (Y/N)", 
                            default_yes=True
                        )
                        # --- END MODAL DIALOG ---

                        # Restore stdscr properties after modal closes
                        stdscr.timeout(50) 
                        stdscr.keypad(True)
                        curses.curs_set(0)
                        stdscr.clear() # Clear potential modal remnants
                        
                        if modal_result is None: 
                            break
                        elif modal_result is False: 
                            proceed = False
                            log_lines.append(format_log({"action": "STATUS", "filename": "Process", "path": "Aborted", "result": "Cancelled by user."}))
                            
                    
                    if proceed:
                        # 4. Start the worker thread
                        is_running = True
                        log_lines.append(format_log({"action": "STATUS", "filename": "Process", "path": "Execution", "result": "Starting worker thread..."}))
                        
                        t = threading.Thread(
                            target=run_recovery_process,
                            args=(rmf_root, src, patch, target, log_queue)
                        )
                        t.start()
                    

                elif 0 <= focus_index < NUM_INPUTS:
                    # Pressing Enter on an input field moves focus down
                    focus_index = min(NUM_INPUTS, focus_index + 1)


            # --- Text Editing (If focus is on an input field) ---
            if 0 <= focus_index < NUM_INPUTS and not is_running:
                key_to_edit = INPUT_FIELDS[focus_index][1]
                current_value = input_values.get(key_to_edit, "")
                
                if 32 <= c <= 126: 
                    input_values[key_to_edit] = current_value + chr(c)
                
                elif c in (curses.KEY_BACKSPACE, 127, 8):
                    input_values[key_to_edit] = current_value[:-1]
                
                # Re-draw input panel to reflect changes
                draw_input_panel(input_win, input_values, focus_index, W)
                input_win.refresh()


        except curses.error:
            pass
        
        except Exception as e:
            log_lines.append(format_log({"action": "FATAL", "filename": "UI", "path": "", "result": f"Exception: {str(e)}"}))
            is_running = False
            stdscr.addstr(H - 1, 1, "FATAL ERROR. Press 'q' to quit.")
            stdscr.refresh()
            break

def _run_app():
    """Wrapper function to initialize and run the curses application."""
    try:
        curses.wrapper(main)
    except Exception as e:
        print(f"An error occurred in the Curses application: {e}", file=sys.stderr)
        
if __name__ == "__main__":
    _run_app()