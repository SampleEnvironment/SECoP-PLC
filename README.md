# SECoP-PLC

This repository contains a CODESYS library and a PLC code generator tool for creating a SEC Node on a CODESYS-based PLC and configuring the mapping between the SECoP layer and the PLC-controlled process.

For detailed documentation, examples and guides, please refer to the Wiki.

---

## 1. What is inside and how to use it

This repository currently contains two main parts:

### `project/`
CODESYS project containing the base PLC SEC Node library.  
To be managed from the CODESYS IDE only, using its Git integration.

### `code-generator/`
Python-based code generator for creating PLC code automatically from a user configuration file.

The configuration file contains:
- the SECoP node structure designed by the user
- additional PLC tooling information required for automatic code generation

The generator is intended to be used from a Python IDE such as PyCharm.

It produces:
- a validation report
- XML files containing PLC code (importable from the PLC IDE)
- a task list for manual PLC integration work

The validation report is the result of applying the project business rules to the input configuration file.  
It provides a list of warnings and errors that require attention before continuing.
PLC code is not generated while validation errors still exist.
Once code generation succeeds, the task list identifies the remaining manual PLC work required to complete the integration.

Please refer to the Wiki for more detailed documentation, including:

- tool description
- PLC SEC Node creation guide
- configuration file guide
- business rules
- validation report examples
- task list examples

---

## 2. Current supported version

The current CODESYS SECoP library version is **1.0.0.0**.

From the PLC IDE, the library version can be obtained using:

`SECoP.GetLibVersionNumber()`

where `SECoP` is the namespace shown in the Library Manager.

In the code generator, the file `src/codegen/utils/constants.py` defines:

`GC_DW_MAX_LIB_VERSION`

This constant indicates the maximum CODESYS library version for which the code generator is considered compatible.

If the CODESYS library evolves beyond the version supported by the code generator, the generated PLC code will still be produced, but the imported project will emit the following warning when compiled in the PLC IDE:

`SECOP library is newer than supported by the code generator.`

---

## 3. Steps required to update the CODESYS library

1. **Open the project from the CODESYS IDE**
2. **Configure Git inside the IDE**
   
   Local repository: Select an empty directory
   
   Remote repository: https://github.com/SampleEnvironment/SECoP-PLC
4. **Clone the remote repository and work from there**

Once the library has been updated, update its version number and tick the 'Release' box on the 'Project Information' settings, and commit/push the new version describing the modifications on the changes log

---

## 4. Steps to create your own PLC SEC Node

1. **Prepare the PLC project if required**
   - From the PLC IDE, install and add the required libraries, such as SECoP and JSON utilities.
   - Configure the required project defines in the compile options, for example `SCHNEIDER_ELECTRIC`.
   - Set the relevant parameters in the GPL list according to the controller capabilities, such as TCP buffer sizes.

2. **Design the SEC Node structure**
   - Define the SECoP node structure according to the SECoP protocol specification.

3. **Prepare the configuration file**
   - Create the configuration file containing the SECoP node structure together with the required PLC tooling information.
   - Refer to the configuration file guide in the Wiki.

4. **Run the code generator**
   - Execute the code generator, for example:

     ```bash
     python main.py --config inputs/secnodeplc_demo_config.json --out outputs/runs
     ```

   - Review the validation report.
   - Fix validation errors and complete any missing configuration fields.

5. **Import the generated outputs into the PLC project**
   - Import all generated PLCopenXML files containing the SEC Node code into the PLC project.

6. **Complete the remaining PLC implementation using the task list**
   - Use the generated task list to complete the remaining pieces of code.
   - Refer to the PLC SEC Node demo project as a reference.

7. **Build the project**
   - Clean all
   - Build all
   - Check for SECoP library version warnings

8. **Test the SEC Node**
   - Run a SECoP client
   - Connect to the SEC Node
   - Exchange SECoP messages and verify correct behaviour
