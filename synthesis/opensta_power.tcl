# Activity-annotated power of a mapped netlist.
#
# Activity comes from a zero-delay gate-level simulation VCD of the same
# netlist, so glitch power is NOT included. Power uses the Nangate45 typical
# liberty internal-power and pin-capacitance tables; there are no wire
# parasitics and the clock is ideal (no clock tree).
#
# Required environment variables:
#   LIBERTY NETLIST TOP PERIOD VCD VCD_SCOPE OUTPREFIX
# Writes OUTPREFIX.power.txt and OUTPREFIX.annotation.txt, and
# OUTPREFIX.instances.txt (power of every cell) if REPORT_INSTANCES is set.

read_liberty $::env(LIBERTY)
read_verilog $::env(NETLIST)
link_design $::env(TOP)

create_clock -name clk -period $::env(PERIOD) [get_ports clk]
set data_inputs [list]
foreach port [all_inputs] {
    set name [get_full_name $port]
    if {$name ne "clk" && $name ne "rst_n"} {
        lappend data_inputs $port
    }
}
set_input_transition 0.05 $data_inputs
set_input_delay 0.0 -clock clk $data_inputs
set_load 0.01 [all_outputs]
set_output_delay 0.0 -clock clk [all_outputs]

read_vcd -scope $::env(VCD_SCOPE) $::env(VCD)

report_activity_annotation > "$::env(OUTPREFIX).annotation.txt"
report_power -digits 6 > "$::env(OUTPREFIX).power.txt"
if {[info exists ::env(REPORT_INSTANCES)]} {
    report_power -instances [get_cells -hierarchical *] -digits 8 \
        > "$::env(OUTPREFIX).instances.txt"
}
