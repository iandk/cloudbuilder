#!/bin/bash

# Get the directory of the current script
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"

apt install -y jq dialog

# Define function to ask user for input
function ask_user_input() {
  # Get a list of available OS template scripts in the current directory
  os_template_scripts=( $(ls $SCRIPT_DIR/*.sh) )

  # Create a dialog checklist string
  checklist_options=""
  index=1
  valid_scripts=()
  for script in "${os_template_scripts[@]}"; do
    script_basename="$(basename "$script" .sh)"  # Remove .sh suffix from the script name
    if [[ "$script_basename" != "main" ]] && [[ "$script_basename" != "base" ]]; then
      checklist_options="$checklist_options $index $script_basename off"
      valid_scripts+=("$script")
      index=$((index+1))
    fi
  done

  # Show the dialog with the checklist
  os_template_nums=$(dialog --stdout --checklist "Which OS templates do you want to build?" 20 60 $((index-1)) $checklist_options)

  # If the user cancels the dialog, exit the script
  if [ $? -ne 0 ]; then
    exit 1
  fi

  # Split user input into an array
  IFS=' ' read -r -a os_template_nums_array <<< "$os_template_nums"

  # Filter selected scripts
  selected_scripts=()
  for num in "${os_template_nums_array[@]}"; do
    selected_scripts+=("${valid_scripts[$((num-1))]}")
  done

  os_template_scripts=("${selected_scripts[@]}")
}

# Call ask_user_input function to get user input
ask_user_input

clear

# Install required package
apt update && apt install -y libguestfs-tools

# Call selected scripts
for script in "${os_template_scripts[@]}"; do
  if [ ! -f "$script" ]; then
    echo "Script not found: $script"
    exit 1
  fi
  bash "$script"
done
