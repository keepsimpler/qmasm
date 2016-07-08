#! /usr/bin/env python

##################################################
# D-Wave quantum machine instruction "assembler" #
# By Scott Pakin <pakin@lanl.gov>                #
##################################################

import qasm
import os
import os.path
import string
import sys

# Parse the command line.
cl_args = qasm.parse_command_line()

# Specify the minimum distinguishable difference between energy readings.
min_energy_delta = 0.005

# Parse the original input file(s) into an internal representation.
qasm.parse_files(cl_args.input)

# Parse the variable pinnings specified on the command line.  Append these to
# the program.
if cl_args.pin != None:
    qasm.parse_pin(cl_args.pin)

# Walk the statements in the program, processing each in turn.
for stmt in qasm.program:
    stmt.update_qmi("", qasm.weights, qasm.strengths, qasm.chains, qasm.pinned)

# Store all tallies for later reportage.
logical_stats = {
    "vars":      qasm.next_sym_num + 1,
    "strengths": len(qasm.strengths),
    "eqs":       len(qasm.chains),
    "pins":      len(qasm.pinned)
}

# Convert from QUBO to Ising in case the solver doesn't support QUBO problems.
if cl_args.qubo:
    qasm.convert_to_ising()

# Define a strength for each user-specified chain, and assign strengths
# to those chains.
qasm.assign_chain_strength(cl_args.chain_strength, cl_args.qubo)

# Define a strength for each user-specified pinned variable.
qasm.assign_pin_strength(cl_args.pin_strength, cl_args.qubo)

# Output the chain and pin strengths.
if cl_args.verbose >= 1:
    sys.stderr.write("Computed the following strengths:\n\n")
    sys.stderr.write("    chain: %7.4f\n" % qasm.chain_strength)
    sys.stderr.write("    pin:   %7.4f\n" % qasm.pin_strength)
    sys.stderr.write("\n")

# Use a helper bit to help pin values to true or false.
qasm.pin_qubits()

# Convert chains to aliases where possible.
if cl_args.O:
    # Say what we're about to do
    if cl_args.verbose >= 2:
        sys.stderr.write("Replaced chains of equally weighted qubits with aliases:\n\n")
        sys.stderr.write("  %6d logical qubits before optimization\n" % (qasm.next_sym_num + 1))

    # Replace chains with aliases wherever we can.
    qasm.convert_chains_to_aliases()

    # Summarize what we just did.
    if cl_args.verbose >= 2:
        sys.stderr.write("  %6d logical qubits after optimization\n\n" % (qasm.next_sym_num + 1))

# This is a good time to update our logical statistics.
logical_stats["vars"] = qasm.next_sym_num + 1

# Complain if we have no weights and no strengths.
if len(qasm.weights) == 0 and len(qasm.strengths) == 0:
    abend("Nothing to do (no weights or strengths specified)")

# Output a normalized input file.
if cl_args.verbose >= 2:
    # Weights
    sys.stderr.write("Canonicalized the input file:\n\n")
    for q in sorted(qasm.weights.keys()):
        sys.stderr.write("    q%d %.20g\n" % (q + 1, qasm.weights[q]))
    sys.stderr.write("\n")

    # Chains
    if len(qasm.chains) > 0:
        for qs in sorted(qasm.chains.keys()):
            sys.stderr.write("    q%d = q%d\n" % (qs[0], qs[1]))
        sys.stderr.write("\n")

    # Strengths (those that are not chains)
    for qs in sorted(qasm.strengths.keys()):
        if not qasm.chains.has_key(qs):
            sys.stderr.write("    q%d q%d %.20g\n" % (qs[0] + 1, qs[1] + 1, qasm.strengths[qs]))
    sys.stderr.write("\n")

    # Map each canonicalized name to one or more original symbols.
    canon2syms = [[] for _ in range(len(qasm.sym2num))]
    max_sym_name_len = 8
    for s, n in qasm.sym2num.items():
        canon2syms[n].append(s)
        max_sym_name_len = max(max_sym_name_len, len(repr(canon2syms[n])) - 1)

    # Output the mapping we just computed.
    sys.stderr.write("Constructed a key to the above:\n\n")
    sys.stderr.write("    Canonical  %-*s\n" % (max_sym_name_len, "Original"))
    sys.stderr.write("    ---------  %s\n" % ("-" * max_sym_name_len))
    for i in range(len(canon2syms)):
        if canon2syms[i] == []:
            continue
        name_list = string.join(sorted(canon2syms[i]))
        sys.stderr.write("    q%-8d  %s\n" % (i + 1, name_list))
    sys.stderr.write("\n")

# Establish a connection to the D-Wave, and use this to talk to a solver.  We
# rely on the qOp infrastructure to set the environment variables properly.
qasm.connect_to_dwave()

# Output most or all solver properties.
if cl_args.verbose >= 1:
    # Determine the width of the widest key.
    max_key_len = len("Parameter")
    ext_solver_properties = {}
    try:
        L, M, N = qasm.chimera_topology(qasm.solver)
        ext_solver_properties["chimera_toplogy_M_N_L"] = [M, N, L]
    except KeyError:
        pass
    ext_solver_properties.update(qasm.solver.properties)
    solver_props = ext_solver_properties.keys()
    solver_props.sort()
    for k in solver_props:
        max_key_len = max(max_key_len, len(k))

    # Output either "short" values (if verbose = 1) or all values (if
    # verbose > 1).
    short_value_len = 70 - max_key_len
    sys.stderr.write("Encountered the following solver properties:\n\n")
    sys.stderr.write("    %-*s  Value\n" % (max_key_len, "Parameter"))
    sys.stderr.write("    %s  -----\n" % ("-" * max_key_len))
    for k in solver_props:
        val_str = repr(ext_solver_properties[k])
        if cl_args.verbose >= 2 or len(val_str) <= short_value_len:
            sys.stderr.write("    %-*s  %s\n" % (max_key_len, k, val_str))
    sys.stderr.write("\n")

# Embed the problem onto the D-Wave.
qasm.embed_problem_on_dwave(cl_args.verbose)

# If told to optimize the layout, iteratively search for a better embedding.
if cl_args.O:
    qasm.optimize_dwave_layout(cl_args.verbose)

# Set all chains to the user-specified strength then combine
# user-specified chains with embedder-created chains.
qasm.update_strengths_from_chains()
if cl_args.verbose >= 2:
    sys.stderr.write("Introduced the following new chains:\n\n")
    new_chains = qasm.get_chains()
    if len(new_chains) == 0:
        sys.stderr.write("    [none]\n")
    else:
        for c in new_chains:
            num1, num2 = c
            if num1 > num2:
                num1, num2 = num2, num1
            sys.stderr.write("    %4d = %4d\n" % (num1, num2))
    sys.stderr.write("\n")

# Map each logical qubit to one or more symbols.
num2syms = [[] for _ in range(len(qasm.sym2num))]
max_sym_name_len = 7
for s, n in qasm.sym2num.items():
    if cl_args.verbose >= 2 or "$" not in s:
        num2syms[n].append(s)
    max_sym_name_len = max(max_sym_name_len, len(repr(num2syms[n])) - 1)

# Output the embedding.
new_embedding = qasm.get_embedding()
if cl_args.verbose >= 1:
    sys.stderr.write("Established a mapping from logical to physical qubits:\n\n")
    sys.stderr.write("    Logical  %-*s  Physical\n" % (max_sym_name_len, "Name(s)"))
    sys.stderr.write("    -------  %s  --------\n" % ("-" * max_sym_name_len))
    for i in range(len(new_embedding)):
        if num2syms[i] == []:
            continue
        name_list = string.join(sorted(num2syms[i]))
        phys_list = string.join(["%4d" % e for e in sorted(new_embedding[i])])
        sys.stderr.write("    %7d  %-*s  %s\n" % (i, max_sym_name_len, name_list, phys_list))
    sys.stderr.write("\n")
else:
    # Even at zero verbosity, we still note the logical-to-physical mapping.
    log2phys_comments = []
    for i in range(len(new_embedding)):
        if num2syms[i] == []:
            continue
        name_list = string.join(num2syms[i])
        phys_list = string.join(["%d" % e for e in sorted(new_embedding[i])])
        log2phys_comments.append("# %s --> %s" % (name_list, phys_list))
    log2phys_comments.sort()
    sys.stderr.write("\n".join(log2phys_comments) + "\n")

# Output some statistics about the embedding.
combined_strengths = qasm.get_strengths()
if cl_args.verbose >= 1:
    # Output a table.
    phys_wts = [elt for lst in new_embedding for elt in lst]
    new_chains = qasm.get_chains()
    sys.stderr.write("Computed the following statistics of the logical-to-physical mapping:\n\n")
    sys.stderr.write("    Type      Metric          Value\n")
    sys.stderr.write("    --------  --------------  -----\n")
    sys.stderr.write("    Logical   Variables       %5d\n" % logical_stats["vars"])
    sys.stderr.write("    Logical   Strengths       %5d\n" % logical_stats["strengths"])
    sys.stderr.write("    Logical     Equivalences  %5d\n" % logical_stats["eqs"])
    sys.stderr.write("    Logical     Pins          %5d\n" % logical_stats["pins"])
    sys.stderr.write("    Physical  Qubits          %5d\n" % len(phys_wts))
    sys.stderr.write("    Physical  Couplers        %5d\n" % len(combined_strengths))
    sys.stderr.write("    Physical    Chains        %5d\n" % len(new_chains))
    sys.stderr.write("\n")

    # Output some additional chain statistics.
    chain_lens = [len(c) for c in new_embedding]
    max_chain_len = 0
    if chain_lens != []:
        max_chain_len = max(chain_lens)
    num_max_chains = len([l for l in chain_lens if l == max_chain_len])
    sys.stderr.write("    Maximum chain length = %d (occurrences = %d)\n\n" % (max_chain_len, num_max_chains))

# Manually scale the weights and strengths so Qubist doesn't complain.
qasm.scale_weights_strengths(cl_args.verbose)

# Output a file in any of a variety of formats.
if cl_args.output != "<stdout>" or not cl_args.run:
    qasm.write_output(cl_args.output, cl_args.format, cl_args.qubo)

# If we weren't told to run anything we can exit now.
if not cl_args.run:
    sys.exit(0)

# Submit the problem to the D-Wave.
if cl_args.verbose >= 1:
    sys.stderr.write("Submitting the problem to the %s solver.\n\n" % qasm.solver_name)
answer, final_answer = qasm.submit_dwave_problem(cl_args.samples, cl_args.anneal_time)

# Output solver timing information.
if cl_args.verbose >= 1:
    try:
        timing_info = answer["timing"].items()
        sys.stderr.write("    %-30s %-10s\n" % ("Measurement", "Value (us)"))
        sys.stderr.write("    %s %s\n" % ("-" * 30, "-" * 10))
        for timing_value in timing_info:
            sys.stderr.write("    %-30s %10d\n" % timing_value)
        sys.stderr.write("\n")
    except KeyError:
        # Not all solvers provide timing information.
        pass

# Define a class to represent a valid solution.
class ValidSolution:
    "Represent a valid ground state of a spin system."

    def __init__(self, soln, energy):
        self.solution = soln
        self.energy = energy
        self.names = []   # List of names for each named row
        self.spins = []   # Spin for each named row
        self.id = 0       # Map from spins to an int
        for q in range(len(soln)):
            if num2syms[q] == []:
                continue
            self.names.append(string.join(num2syms[q]))
            self.spins.append(soln[q])
            self.id = self.id*2 + soln[q]

# Define a function that says whether an answer contains no broken pins and no
# broken (user-specified) chains.
def answer_is_intact(answer):
    # Reject broken pins.
    bool2spin = [-1, +1]
    for pnum, pin in qasm.pinned:
        if answer[pnum] != bool2spin[pin]:
            return False

    # Reject broken chains.
    for q1, q2 in qasm.chains.keys():
        if answer[q1] != answer[q2]:
            return False

    # The answer looks good!
    return True

# Determine the set of solutions to output.
final_answer = [a for a in final_answer if answer_is_intact(a)]
if len(final_answer) == 0:
    print "No valid solutions found,"
    sys.exit(0)
energies = answer["energies"]
n_low_energies = len([e for e in energies if abs(e - energies[0]) < min_energy_delta])
if cl_args.verbose >= 2:
    n_solns_to_output = len(final_answer)
else:
    n_solns_to_output = min(n_low_energies, len(final_answer))
id2solution = {}   # Map from an int to a solution
for snum in range(n_solns_to_output):
    soln = ValidSolution(final_answer[snum], energies[snum])
    if not id2solution.has_key(soln.id):
        id2solution[soln.id] = soln

# Output information about the raw solutions.
if cl_args.verbose >= 1:
    sys.stderr.write("Number of solutions found:\n\n")
    sys.stderr.write("    %6d total\n" % len(energies))
    sys.stderr.write("    %6d with no broken chains or broken pins\n" % len(final_answer))
    sys.stderr.write("    %6d in the ground state\n" % n_low_energies)
    sys.stderr.write("    %6d excluding duplicate variable assignments\n" % len(id2solution))
    sys.stderr.write("\n")

# Output energy tallies.  We first recompute these because some entries seem to
# be multiply listed.
if cl_args.verbose >= 2:
    tallies = answer["num_occurrences"]
    new_energy_tallies = {}
    for i in range(len(energies)):
        e = float(energies[i])
        t = int(tallies[i])
        try:
            new_energy_tallies[e] += t
        except KeyError:
            new_energy_tallies[e] = t
    new_energies = new_energy_tallies.keys()
    new_energies.sort()
    sys.stderr.write("Energy histogram:\n\n")
    sys.stderr.write("    Energy      Tally\n")
    sys.stderr.write("    ----------  ------\n")
    for e in new_energies:
        sys.stderr.write("    %10.4f  %6d\n" % (e, new_energy_tallies[e]))
    sys.stderr.write("\n")

# Output to standard output (regardless of --output) the solutions with no
# broken chains.
bool_str = {-1: "False", +1: "True"}
sorted_solns = [id2solution[s] for s in sorted(id2solution.keys())]
for snum in range(len(sorted_solns)):
    print "Solution #%d (energy = %.2f):\n" % (snum + 1, sorted_solns[snum].energy)
    print "    %-*s  Spin  Boolean" % (max_sym_name_len, "Name(s)")
    print "    %s  ----  -------" % ("-" * max_sym_name_len)
    soln = sorted_solns[snum]
    output_lines = []
    for q in range(len(soln.spins)):
        names = soln.names[q]
        spin = soln.spins[q]
        output_lines.append("    %-*s  %+4d  %-7s" % (max_sym_name_len, names, spin, bool_str[spin]))
    output_lines.sort()
    print "\n".join(output_lines), "\n"