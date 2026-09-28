# Clocked pre-layout timing, split by path class.
#
# Timing constraints:
# - one clock on port clk, period PERIOD ns
# - zero input/output delay relative to clk
# - 50 ps input transition, 10 fF output load
# - async reset excluded as a timing startpoint
# - no wire-load model (pre-layout, no parasitics)
#
# Required environment variables: LIBERTY NETLIST TOP PERIOD OUTPREFIX
# Writes:
#   OUTPREFIX.<class>.txt   worst max-delay path of each class (or "none")
#   OUTPREFIX.summary.txt   worst slack / TNS over all constrained paths
#   OUTPREFIX.worst.txt     human-readable worst path

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

if {[llength [get_ports -quiet rst_n]] > 0} {
    set_false_path -from [get_ports rst_n]
}

set prefix $::env(OUTPREFIX)
set reg_clk [all_registers -clock_pins]
set reg_d [all_registers -data_pins]

proc write_class {prefix cls from to} {
    set f "${prefix}.${cls}.txt"
    if {[llength $from] == 0 || [llength $to] == 0} {
        set fh [open $f w]
        puts $fh "none"
        close $fh
        return
    }
    report_checks -path_delay max -from $from -to $to \
        -group_path_count 1 -digits 6 > $f
}

write_class $prefix in2reg $data_inputs $reg_d
write_class $prefix reg2reg $reg_clk $reg_d
write_class $prefix reg2out $reg_clk [all_outputs]
write_class $prefix in2out $data_inputs [all_outputs]

set fh [open "${prefix}.summary.txt" w]
puts $fh "period_ns [format %.6f $::env(PERIOD)]"
# OpenSTA returns these in seconds.
puts $fh "worst_slack_ns [format %.6f [expr {1e9 * [sta::worst_slack_cmd max]}]]"
puts $fh "tns_ns [format %.6f [expr {1e9 * [sta::total_negative_slack_cmd max]}]]"
puts $fh "registers [llength [all_registers]]"
close $fh

report_checks -path_delay max -group_path_count 1 \
    -fields {slew cap fanout} -digits 4 > "${prefix}.worst.txt"
