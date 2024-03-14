import re
import argparse
from pathlib import Path


def parse_matlab_file(matlab_file_path):
    with open(matlab_file_path, 'r') as file:
        matlab_function = file.read()

    # Extract function name and arguments
    match = re.match(r"function \[\] = (\w+)\((.*)\)", matlab_function)
    if not match:
        raise ValueError("Invalid MATLAB function format")

    function_name = match.group(1)

    # Extract inputParser parameters
    input_parser_params_addRequired = re.findall(r"ip\.addRequired\((.*?)(?:\s*,(.*))?\);", matlab_function)
    input_parser_params_addParameter = re.findall(r"ip\.addParameter\((.*)\s*,(.*)\s*,(.*)\);", matlab_function)

    # Concatenate the capture groups and remove spaces
    input_parser_params = [",".join(param).replace(" ", "") for param in input_parser_params_addRequired]
    input_parser_params += [",".join(param).replace(" ", "") for param in input_parser_params_addParameter]

    return function_name, input_parser_params


def generate_function(function_name, input_parser_params):
    if "_parser" in function_name:
        function_name = function_name.replace("_parser", "")
    functionString = "import subprocess\n\n\ndef " + function_name + "("

    # Count the number of strings with only one comma
    numRequired = sum(param.count(',') == 1 for param in input_parser_params)
    addRequired = True
    first_strings = [re.search(r"'([^']*)'", param).group(1) for param in input_parser_params]
    for i in range(numRequired):
        functionString = functionString + first_strings[i] + ", "
    functionString = functionString + f"**kwargs):\n    function_name = \"{function_name}\"\n    {function_name}_dict = {{\n        "
    varTypes = [""] * len(input_parser_params)
    for i, (param, firstString) in enumerate(zip(input_parser_params, first_strings)):
        extracted_string = ""
        if i >= numRequired:
            extracted_string = re.search(r",'?(.*?)'?,@", param).group(1)
        if "@ischar" in param or "@(x)ischar(x)" in param or "ismember" in param or "strcmpi" in param:
            varTypes[i] = "char"
        elif "iscell" in param:
            extracted_string = extracted_string.replace("{", "[")
            extracted_string = extracted_string.replace("}", "]")
            varTypes[i] = "cell"
        elif "islogical" in param:
            if "[" in extracted_string and bool(re.search(r'\[[^,]+,.*]', extracted_string)) :
                extracted_string = '[' + ','.join(
                    [element.strip().capitalize() for element in extracted_string[1:-1].split(',')]) + ']'
                varTypes[i] = "logicalArr"
            else:
                if "~" in extracted_string:
                    extracted_string = extracted_string.replace("~","")
                    if extracted_string == "true":
                        extracted_string = "false"
                    else:
                        extracted_string = "true"
                varTypes[i] = "logical"
                extracted_string = extracted_string.capitalize()
        elif "isnumeric" in param or "isscalar" in param or "isvector" in param:
            if "isvector" in param or bool(re.search(r'\[[^,]+,.*]', extracted_string)) or "lastStart" in param:
                varTypes[i] = "numericArr"
            else:
                varTypes[i] = "numericScalar"
        else:
            varTypes[i] = "err"
        if i < numRequired:
            continue
        if varTypes[i] == "char":
            extracted_string = f"\"{extracted_string}\""
        if firstString == "parseCluster":
            extracted_string = "False"
        functionString = functionString + f"\"{firstString}\": [kwargs.get(\"{firstString}\", {extracted_string}), \"{varTypes[i]}\"],\n        "

    functionString = functionString[:-10] + "\n    }\n\n    "
    functionString += "mccMasterLoc = \"/home/matt/LLSM_Processing_GUI/LLSM5DTools/mcc/linux/run_mccMaster.sh\"\n    "
    functionString += "matlabRuntimeLoc = \"/home/matt/LLSM_Processing_GUI/MATLAB_Runtime/R2023a\"\n    "
    for i, firstString in enumerate(first_strings[:numRequired]):
        if varTypes[i] == "cell":
            functionString += f"{firstString}String = \"{{\" + \",\".join(f\"\'{{item}}\'\" for item in {firstString}) + \"}}\"\n    "
        if "numeric" in varTypes[i]:
            functionString += f"{firstString}String = \"[\" + \",\".join(str(item) for item in {firstString}) + \"]\"\n    "
        else:
            # Assume it is a cell array
            functionString += f"{firstString}String = \"{{\" + \",\".join(f\"\'{{item}}\'\" for item in {firstString}) + \"}}\"\n    "
    functionString += "cmdString = f\"\\\"{mccMasterLoc}\\\" \\\"{matlabRuntimeLoc}\\\" {function_name} "
    for i, firstString in enumerate(first_strings[:numRequired]):
        if varTypes[i] == "char":
            functionString += f"\\\"{{{firstString}}}\\\" "
        else:
            functionString += f"\\\"{{{firstString}String}}\\\" "
    functionString += "\"\n    "
    functionString += f"""
    for key, value in {function_name}_dict.items():
        if value[1] == "char":
            if not value[0]:
                continue
            cmdString += f"\\\"{{key}}\\\" \\\"{{value[0]}}\\\" "
        elif value[1] == "cell":
            cellString = "{{" + ",".join(f"'{{item}}'" for item in value[0]) + "}}"
            cmdString += f"\\\"{{key}}\\\" \\\"{{cellString}}\\\" "
        elif value[1] == "logicalArr":
            logicalArrString = "[" + ",".join(str(item) for item in value[0]) + "]"
            cmdString += f"\\\"{{key}}\\\" \\\"{{str(logicalArrString).lower()}}\\\" "
        elif value[1] == "logical":
            cmdString += f"\\\"{{key}}\\\" {{str(value[0]).lower()}} "
        elif value[1] == "numericArr":
            if not value[0]:
                continue
            numericArrString = "[" + ",".join(str(item) for item in value[0]) + "]"
            cmdString += f"\\\"{{key}}\\\" \\\"{{numericArrString}}\\\" "
        elif value[1] == "numericScalar":
            if type(value[0]) is list:
                if not value[0]:
                    continue
                else:
                    value[0] = value[0][0]
            cmdString += f"\\\"{{key}}\\\" {{value[0]}} "
        else:
            continue
    process = subprocess.Popen(cmdString, shell=True)
    process.wait()
    """
    output_file = Path(f"/home/matt/PyLLSM5DTools/src/{function_name}.py")
    output_file.parent.mkdir(exist_ok=True, parents=True)
    output_file.write_text(f"{functionString}")

    return


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Generate command for calling MATLAB function.')
    parser.add_argument('matlab_file', type=str, help='Path to MATLAB file')
    args = parser.parse_args()

    function_name, input_parser_params = parse_matlab_file(args.matlab_file)

    generate_function(function_name, input_parser_params)
