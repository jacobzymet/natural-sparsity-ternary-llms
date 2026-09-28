`timescale 1ns/1ps

// Trace-driven GEMV testbench for switching-activity measurement of the
// five-trit streaming engine. Works on RTL or on a flattened gate netlist.
//
// Plusargs: +DIR=<workload dir> +ROWS=<n> +GROUPS=<K/5> +PERIOD=<ns> [+VCD=<file>]
// Workload files come from scripts/power_workload.py.
module tb_power_tace;
    logic clk = 0;
    logic rst_n = 0;
    logic start = 0;
    logic valid = 0;
    logic last = 0;
    logic [39:0] activations = '0;
    logic [7:0] packed_weights = '0;
    logic signed [23:0] dot;
    logic done;

    ternary_five_trit_stream5_accum dut (
        .clk(clk), .rst_n(rst_n), .start(start), .valid(valid), .last(last),
        .activations(activations), .packed_weights(packed_weights),
        .dot(dot), .done(done)
    );

    string dir;
    string vcd;
    integer rows, groups, r, g, checked, errors;
    real period, drive;
    logic [39:0] acts [0:4095];
    logic [7:0] tace [0:262143];
    logic [63:0] rowinfo [0:1023];

    initial begin
        period = 2.0;
        void'($value$plusargs("PERIOD=%f", period));
    end
    always #(period / 2.0) clk = ~clk;

    always @(negedge clk) begin
        if (rst_n && done) begin
            if ($signed(dot) !== $signed(rowinfo[checked][55:32])) begin
                $display("FAIL row %0d dot=%0d expected=%0d", checked, $signed(dot),
                         $signed(rowinfo[checked][63:32]));
                errors = errors + 1;
            end
            checked = checked + 1;
        end
    end

    initial begin
        checked = 0;
        errors = 0;
        if (!$value$plusargs("DIR=%s", dir)) $fatal(1, "missing +DIR");
        if (!$value$plusargs("ROWS=%d", rows)) $fatal(1, "missing +ROWS");
        if (!$value$plusargs("GROUPS=%d", groups)) $fatal(1, "missing +GROUPS");
        $readmemh({dir, "/acts.memh"}, acts);
        $readmemh({dir, "/tace.memh"}, tace);
        $readmemh({dir, "/rows.memh"}, rowinfo);
        drive = 0.1 * period;

        repeat (2) @(posedge clk);
        #(drive) rst_n = 1;
        if ($value$plusargs("VCD=%s", vcd)) begin
            $dumpfile(vcd);
            $dumpvars(2, dut);
        end

        // Inputs change with nonblocking assignments in the same time step as
        // the clock edge, as if driven by registers on the same clock. A
        // later drive time would make register-fed logic evaluate twice per
        // cycle in zero-delay simulation.
        for (r = 0; r < rows; r = r + 1) begin
            @(posedge clk);
            start <= 1; valid <= 0; last <= 0;
            for (g = 0; g < groups; g = g + 1) begin
                @(posedge clk);
                start <= 0;
                valid <= 1;
                last <= (g == groups - 1);
                activations <= acts[g];
                packed_weights <= tace[r * groups + g];
            end
        end
        @(posedge clk);
        valid <= 0; last <= 0;
        repeat (2) @(posedge clk);
        $dumpoff;
        if (errors != 0 || checked != rows) begin
            $display("FAIL: %0d errors, %0d of %0d rows checked", errors, checked, rows);
            $finish(1);
        end
        $display("PASS: five-trit power trace, %0d rows x %0d groups", rows, groups);
        $finish(0);
    end
endmodule
