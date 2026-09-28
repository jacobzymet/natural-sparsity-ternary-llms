`timescale 1ns/1ps

// Test and switching-activity testbench for bitcos_presence_repack (RTL or
// gate netlist). Every output row is checked against the input bytes.
//
// Random mode (no +DIR): random bytes, random gaps in byte_valid, and random
// restarts (start with and without a byte, mid-row).
//
// Trace mode (+DIR=<workload dir> +ROWS=<n> +GROUPS=<K/5>): the byte-packed
// presence bitmap of a power workload (scripts/power_workload.py) is fed as
// one weight matrix. +DUTY=5 feeds a byte on 5 of every 8 cycles, the rate
// one five-weight-per-cycle engine consumes; +DUTY=8 feeds a byte every
// cycle. Optional +PERIOD=<ns> +VCD=<file>.
module tb_presence_repack;
    logic clk = 0;
    logic rst_n = 0;
    logic start = 0;
    logic byte_valid = 0;
    logic [7:0] presence_byte = '0;
    logic row_valid;
    logic [39:0] row;

    bitcos_presence_repack dut (
        .clk(clk), .rst_n(rst_n), .start(start), .byte_valid(byte_valid),
        .presence_byte(presence_byte), .row_valid(row_valid), .row(row)
    );

    string dir, vcd;
    real period, drive, t_on;
    integer rows, groups, duty, nbytes, i, k, errors, checked, fill, expected_rows;
    logic [7:0] pres [0:262143];
    logic [39:0] pending;

    initial begin
        period = 2.0;
        void'($value$plusargs("PERIOD=%f", period));
    end
    always #(period / 2.0) clk = ~clk;

    // Reference: assemble rows from the bytes accepted at each posedge.
    always @(posedge clk) begin
        if (rst_n && byte_valid === 1'b1) begin
            if (start === 1'b1) fill = 0;
            pending[fill*8 +: 8] = presence_byte;
            if (fill == 4) begin
                if (row_valid !== 1'b1 || row !== pending) begin
                    if (errors < 10) $display("FAIL row %0d got valid=%b %h expected %h", checked, row_valid, row, pending);
                    errors = errors + 1;
                end
                checked = checked + 1;
                fill = 0;
            end else begin
                if (row_valid !== 1'b0) begin
                    if (errors < 10) $display("FAIL spurious row_valid at %0t", $time);
                    errors = errors + 1;
                end
                fill = fill + 1;
            end
        end else if (rst_n && row_valid !== 1'b0) begin
            if (errors < 10) $display("FAIL row_valid without byte at %0t", $time);
            errors = errors + 1;
        end else if (rst_n && start === 1'b1) begin
            fill = 0;
        end
    end

    initial begin
        errors = 0; checked = 0; fill = 0;
        drive = 0.1 * period;
        repeat (2) @(posedge clk);
        #(drive) rst_n = 1;

        if ($value$plusargs("DIR=%s", dir)) begin
            if (!$value$plusargs("ROWS=%d", rows)) $fatal(1, "missing +ROWS");
            if (!$value$plusargs("GROUPS=%d", groups)) $fatal(1, "missing +GROUPS");
            duty = 8;
            void'($value$plusargs("DUTY=%d", duty));
            $readmemh({dir, "/presence.memh"}, pres);
            nbytes = rows * groups * 5 / 8;
            if (nbytes % 5 != 0) $fatal(1, "bitmap is not a whole number of rows");
            expected_rows = nbytes / 5;
            if ($value$plusargs("VCD=%s", vcd)) begin
                $dumpfile(vcd);
                $dumpvars(2, dut);
            end
            // Inputs change with nonblocking assignments at the clock edge.
            t_on = $realtime;
            k = 0;
            for (i = 0; k < nbytes; i = i + 1) begin
                @(posedge clk);
                start <= (i == 0);
                if ((i % 8) < duty) begin
                    byte_valid <= 1;
                    presence_byte <= pres[k];
                    k = k + 1;
                end else begin
                    byte_valid <= 0;
                end
            end
            @(posedge clk);
            byte_valid <= 0; start <= 0;
            repeat (2) @(posedge clk);
            $dumpoff;
            $display("window_ns %0.4f", $realtime - t_on);
            if (errors != 0 || checked != expected_rows) begin
                $display("FAIL: %0d errors, %0d of %0d rows", errors, checked, expected_rows);
                $finish(1);
            end
            $display("PASS: presence repack trace duty %0d/8, %0d rows x %0d groups", duty, rows, groups);
            $finish(0);
        end

        for (i = 0; i < 20000; i = i + 1) begin
            @(posedge clk);
            byte_valid <= ($urandom_range(3, 0) != 0);
            presence_byte <= $urandom;
            start <= ($urandom_range(99, 0) == 0);
        end
        @(posedge clk);
        byte_valid <= 0; start <= 0;
        repeat (2) @(posedge clk);
        if (errors != 0 || checked < 2000) begin
            $display("FAIL: %0d errors, %0d rows checked", errors, checked);
            $finish(1);
        end
        $display("PASS: presence repack random, %0d rows", checked);
        $finish(0);
    end
endmodule
