# Fault Mode Presentation
Here is presented the structure of a Fault Mode file, which describes all of the injection made by the the MCP Proxy injector.

## JSON keys and meanings
Each fault is made up by a list of keys:
* **type**: The fault we want to inject. Here are the implemented types:
    * **OP0_nullInjector**: Basically doesn't do anything;
    * **OP1_smallDelta**: The server's response is disturbed by a small delta defined by the parameter **delta_ratio** and it is applied to each word with a probability defined by the **probability_per_word** parameter;
    * **OP2_randomValue**: It works as the small delta operator but instead of disturbing the word, we replace it with a probability given by the **probability_per_word** parameter;
    * **OP3_randomWrongType**: It makes a check on the type of the response and then it returns a casted response with a wrong type;
    * **OP4_errorMessage**: Instead of returning the response, it raises an error message about the unreachability of the tool;
    * **OP5_delay**: The response is returned with a delay which duration is defined by the **dureation** parameter;
    * **OP6_dropCall**: The tool call is dropped without being processed.
* **probability**: Represents the probability distribution by which the faults are selected;
* **targets**: Represents the tools on which we can injcet the fault. It can be either **global** or a **list of tools**;
* **parameters**: Any additional parameter for the fault execution;
* **persistence**: The way the fault is injected. It can be:
    * **TRANSIENT**: The fault is activated just for the current tool call with a fixed probability "activation_p", then it is deactivated;
    * **INTERMITTENT**: The fault is activated with a fixed probability "activation_p", the is deactivated with another fixed probability "deactivation_p";
    * **PERMANENT**: Once activated, the fault stays active forever.

**Example**:
```python
{
      "type": "OP1_smallDelta",
      "probability": 0.20,
      "targets": ["global"],
      "parameters": {
        "delta_ratio": 0.05,
        "probability_per_word": 0.60
        },
      "persistence": { "type": "TRANSIENT", "activation_p": 0.3 }
    }
```

## Benchmark execution with fault mode
We can execute the benchmark with fault injection by adding a fault mode field.

**Example**:
```python
python run_benchmark.py --models gpt-oss-20b:free --tasks-file tasks/single-test-for-debug.json --fault-mode fault_modes/fault_mode_1.json
```

## License

`fault_mode_0.json` (null profile, condition OP0) and `fault_mode_1.json` (calibrated profile, condition OPP) are released under the Creative Commons Attribution 4.0 International license (CC-BY-4.0). See `../DATA-LICENSE` for the full legal text and `../LICENSES-README.md` for the repository-wide license map. When citing the calibrated profile, please cite the accompanying paper; see the `Citation` section of the top-level `README.md` for the BibTeX entry.
