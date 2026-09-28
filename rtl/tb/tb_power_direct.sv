`timescale 1ns/1ps

// Trace-driven GEMV testbench for switching-activity measurement of the
// direct bitmap/sign streaming engine. Works on RTL or on a flattened gate
// netlist.
//
// The engine expects the current and next byte of each stream. Here a
// behavioral pointer per stream supplies them and advances when the engine
// requests it, standing in for byte registers that are NOT part of the
// measured engine.
//
// Define DIRECT_TOP to test a variant with the same ports.
//
// Plusargs: +DIR=<workload dir> +ROWS=<n> +GROUPS=<K/5> +PERIOD=<ns> [+VCD=<file>]
`ifndef DIRECT_TOP
`define DIRECT_TOP ternary_bitcos_stream5_direct_accum
`endif

module tb_power_direct;
    logic clk = 0;
    logic rst_n = 0;
    logic start = 0;
    logic [2:0] initial_presence_offset = '0;
    logic [2:0] initial_sign_offset = '0;
    logic valid = 0;
    logic last = 0;
    logic [39:0] activations = '0;
    logic [7:0] current_presence_byte, next_presence_byte;
    logic [7:0] current_sign_byte, next_sign_byte;
    logic advance_presence_byte, advance_sign_byte;
    logic [2:0] presence_offset, sign_offset;
    logic signed [23:0] dot;
    logic done;

    `DIRECT_TOP dut (
        .clk(clk), .rst_n(rst_n), .start(start),
        .initial_presence_offset(initial_presence_offset),
        .initial_sign_offset(initial_sign_offset),
        .valid(valid), .last(last), .activations(activations),
        .current_presence_byte(current_presence_byte),
        .next_presence_byte(next_presence_byte),
        .current_sign_byte(current_sign_byte),
        .next_sign_byte(next_sign_byte),
        .advance_presence_byte(advance_presence_byte),
        .advance_sign_byte(advance_sign_byte),
        .presence_offset(presence_offset), .sign_offset(sign_offset),
        .dot(dot), .done(done)
    );

    string dir;
    string vcd;
    integer rows, groups, r, g, checked, errors, pp, sp, bytes_per_row;
    logic adv_p, adv_s;
    real period, drive;
    logic [39:0] acts [0:4095];
    logic [7:0] pres [0:262143];
    logic [7:0] sgn [0:262143];
    logic [63:0] rowinfo [0:1023];

    initial begin
        period = 2.0;
        void'($value$plusargs("PERIOD=%f", period));
    end
    always #(period / 2.0) clk = ~clk;

    initial begin
        pp = 0;
        sp = 0;
    end
    assign current_presence_byte = pres[pp];
    assign next_presence_byte = pres[pp + 1];
    assign current_sign_byte = sgn[sp];
    assign next_sign_byte = sgn[sp + 1];

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
        $readmemh({dir, "/presence.memh"}, pres);
        $readmemh({dir, "/signs.memh"}, sgn);
        $readmemh({dir, "/rows.memh"}, rowinfo);
        drive = 0.1 * period;
        bytes_per_row = groups * 5 / 8;

        repeat (2) @(posedge clk);
        #(drive) rst_n = 1;
        if ($value$plusargs("VCD=%s", vcd)) begin
            $dumpfile(vcd);
            $dumpvars(2, dut);
        end

        // Inputs (including the stream pointers) change with nonblocking
        // assignments in the same time step as the clock edge, as if driven
        // by registers on the same clock. Advance requests are sampled at the
        // falling edge, when the engine's combinational outputs are settled.
        for (r = 0; r < rows; r = r + 1) begin
            @(posedge clk);
            start <= 1; valid <= 0; last <= 0;
            pp <= r * bytes_per_row;
            sp <= rowinfo[r][31:0] / 8;
            initial_presence_offset <= 3'd0;
            initial_sign_offset <= rowinfo[r][2:0];
            adv_p = 0;
            adv_s = 0;
            for (g = 0; g < groups; g = g + 1) begin
                @(posedge clk);
                if (adv_p) pp <= pp + 1;
                if (adv_s) sp <= sp + 1;
                start <= 0;
                valid <= 1;
                last <= (g == groups - 1);
                activations <= acts[g];
                @(negedge clk);
                adv_p = advance_presence_byte;
                adv_s = advance_sign_byte;
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
        $display("PASS: direct bitmap/sign power trace, %0d rows x %0d groups", rows, groups);
        $finish(0);
    end
endmodule
