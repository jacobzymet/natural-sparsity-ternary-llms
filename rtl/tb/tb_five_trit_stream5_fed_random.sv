`timescale 1ns/1ps

// Directed + random test of ternary_five_trit_stream5_fed (RTL or gate netlist).
//
// Rows are written into a behavioral byte memory (unused bytes hold random
// garbage) at arbitrary byte addresses and run through the engine with the
// common row protocol: start, PREFILL idle cycles, GROUPS valid cycles. Every
// row's dot product is checked against a reference computed here.
//
// Coverage: zero densities 0.0, 0.2, 0.42, 0.7, 1.0, all-negative rows,
// single-group rows, contiguous back-to-back rows and rows with gaps in
// memory, with and without idle cycles between rows. Start addresses and
// activations are randomized whenever they must be ignored.
module tb_five_trit_stream5_fed_random;
    localparam int ACT_W = 8;
    localparam int ACC_W = 24;
    localparam int AW = 16;
    localparam int PREFILL = 1;
    localparam int MEMB = 1 << AW;
    localparam int MAXROWS = 4096;

    logic clk = 0;
    logic rst_n = 0;
    logic start = 0;
    logic [AW-1:0] start_tace_addr = '0;
    logic valid = 0;
    logic last = 0;
    logic [5*ACT_W-1:0] activations = '0;
    logic tace_rd_en;
    logic [AW-1:0] tace_rd_addr;
    logic [7:0] tace_rd_data = '0;
    logic signed [ACC_W-1:0] dot;
    logic done;

    ternary_five_trit_stream5_fed dut (
        .clk(clk), .rst_n(rst_n), .start(start), .start_tace_addr(start_tace_addr),
        .valid(valid), .last(last), .activations(activations),
        .tace_rd_en(tace_rd_en), .tace_rd_addr(tace_rd_addr), .tace_rd_data(tace_rd_data),
        .dot(dot), .done(done)
    );

    always #1 clk = ~clk;

    logic [7:0] tace_mem [0:MEMB-1];
    logic [39:0] act_mem [0:MEMB-1];
    integer row_addr [0:MAXROWS-1];
    integer row_groups [0:MAXROWS-1];
    integer row_idle [0:MAXROWS-1];
    integer row_expected [0:MAXROWS-1];
    integer nrows, bptr, total_groups;
    integer checked, errors, xerrors, cycles_valid;
    integer i, r, g, zi, k;
    integer zp_list [0:4];

    always @(posedge clk) begin
        if (tace_rd_en === 1'b1)
            tace_rd_data <= tace_mem[tace_rd_addr];
        if (rst_n && ((tace_rd_en !== 1'b0 && tace_rd_en !== 1'b1) ||
                      (tace_rd_en === 1'b1 && $isunknown(tace_rd_addr)))) begin
            if (xerrors < 10) $display("FAIL unknown read request at %0t", $time);
            xerrors = xerrors + 1;
        end
    end

    always @(negedge clk) begin
        if (rst_n) begin
            if (valid) cycles_valid = cycles_valid + 1;
            if (done) begin
                if (checked >= nrows) begin
                    $display("FAIL spurious done");
                    errors = errors + 1;
                end else if ($signed(dot) !== row_expected[checked]) begin
                    if (errors < 20)
                        $display("FAIL row %0d (addr %0d groups %0d) dot=%0d expected=%0d",
                                 checked, row_addr[checked], row_groups[checked],
                                 $signed(dot), row_expected[checked]);
                    errors = errors + 1;
                end
                checked = checked + 1;
            end
        end
    end

    // gap: bytes skipped before the row. mode 0: iid, P(zero) = zp/1000,
    // random signs; mode 1: all -1.
    task add_row(input integer gap, input integer groups, input integer zp,
                 input integer mode, input integer idle);
        integer gg, l, w, a, expv, b, p3;
        logic [39:0] word;
        begin
            bptr = bptr + gap;
            row_addr[nrows] = bptr;
            row_groups[nrows] = groups;
            row_idle[nrows] = idle;
            expv = 0;
            for (gg = 0; gg < groups; gg = gg + 1) begin
                word = '0;
                b = 0;
                p3 = 1;
                for (l = 0; l < 5; l = l + 1) begin
                    a = $urandom_range(255, 0) - 128;
                    word[l*8 +: 8] = a[7:0];
                    if (mode == 1) w = -1;
                    else w = ($urandom_range(999, 0) < zp) ? 0 : (($urandom & 1) ? -1 : 1);
                    b = b + ((w == 0) ? 0 : (w == 1) ? 1 : 2) * p3;
                    p3 = p3 * 3;
                    expv = expv + w * a;
                end
                tace_mem[bptr] = b[7:0];
                act_mem[bptr] = word;
                bptr = bptr + 1;
            end
            row_expected[nrows] = expv;
            nrows = nrows + 1;
            total_groups = total_groups + groups;
        end
    endtask

    initial begin
        nrows = 0; bptr = 0; total_groups = 0;
        checked = 0; errors = 0; xerrors = 0; cycles_valid = 0;
        zp_list[0] = 0; zp_list[1] = 200; zp_list[2] = 420; zp_list[3] = 700; zp_list[4] = 1000;
        for (i = 0; i < MEMB; i = i + 1) tace_mem[i] = $urandom;

        for (zi = 0; zi < 5; zi = zi + 1)
            for (k = 0; k < 20; k = k + 1)
                add_row($urandom_range(3, 0), 1 + $urandom_range(11, 0), zp_list[zi], 0, 0);
        for (k = 0; k < 8; k = k + 1) begin
            add_row(0, 64, 0, 1, 0);
            add_row(1, 64, 1000, 0, 0);
        end
        for (k = 0; k < 40; k = k + 1)
            add_row($urandom_range(1, 0), 1, zp_list[$urandom_range(4, 0)], 0, 0);
        for (k = 0; k < 300; k = k + 1)
            add_row(0, 1 + $urandom_range(39, 0), zp_list[k % 5], (k % 17 == 0) ? 1 : 0,
                    (k % 7 == 3) ? $urandom_range(3, 1) : 0);
        if (bptr > MEMB - 4) $fatal(1, "memory too small");

        repeat (2) @(posedge clk);
        #0.2 rst_n = 1;

        for (r = 0; r < nrows; r = r + 1) begin
            for (k = 0; k < row_idle[r]; k = k + 1) begin
                @(posedge clk);
                start <= 0; valid <= 0; last <= 0;
                start_tace_addr <= $urandom;
                activations <= {$urandom, $urandom};
            end
            @(posedge clk);
            start <= 1; valid <= 0; last <= 0;
            start_tace_addr <= row_addr[r];
            activations <= {$urandom, $urandom};
            repeat (PREFILL) begin
                @(posedge clk);
                start <= 0;
                start_tace_addr <= $urandom;
                activations <= {$urandom, $urandom};
            end
            for (g = 0; g < row_groups[r]; g = g + 1) begin
                @(posedge clk);
                start <= 0;
                valid <= 1;
                last <= (g == row_groups[r] - 1);
                activations <= act_mem[row_addr[r] + g];
                start_tace_addr <= $urandom;
            end
        end
        @(posedge clk);
        valid <= 0; last <= 0;
        repeat (3) @(posedge clk);

        $display("coverage: %0d rows, %0d groups, %0d valid cycles", nrows, total_groups, cycles_valid);
        if (errors != 0 || xerrors != 0 || checked != nrows || cycles_valid != total_groups) begin
            $display("FAIL: %0d errors, %0d unknown requests, %0d of %0d rows checked",
                     errors, xerrors, checked, nrows);
            $finish(1);
        end
        $display("PASS: five-trit fed random, %0d rows", nrows);
        $finish(0);
    end
endmodule
