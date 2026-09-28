`timescale 1ns/1ps

// Directed + random test of ternary_bitcos_stream5_bank_fed (RTL or gate
// netlist), Architecture B: 5-bit-wide presence memory, byte-wide sign memory.
//
// Rows are written into behavioral memories (unused locations hold random
// garbage) and run with the common row protocol: start, PREFILL idle cycles,
// GROUPS valid cycles with no stalls. Every row's dot product is checked
// against a reference computed here.
//
// Coverage:
// - every sign offset x zero densities 0.0, 0.2, 0.42, 0.7, 1.0, several
//   rows each
// - long all-nonzero rows (sign stream advances nearly every cycle), all
//   negative and random signs, at every sign offset
// - long all-zero rows, alternating full/empty groups
// - single-group rows
// - contiguous back-to-back rows with and without idle cycles between rows,
//   and rows starting at random presence addresses
// Start addresses and activations are randomized whenever they must be
// ignored (outside start / valid cycles).
module tb_bitcos_stream5_bank_fed_random;
    localparam int ACT_W = 8;
    localparam int ACC_W = 24;
    localparam int AW = 16;
    localparam int PREFILL = 1;
    localparam int MEMB = 1 << AW;
    localparam int MAXROWS = 4096;
    localparam int MAXGROUPS = 65536;

    logic clk = 0;
    logic rst_n = 0;
    logic start = 0;
    logic [AW-1:0] start_presence_addr = '0;
    logic [AW+2:0] start_sign_bit_addr = '0;
    logic valid = 0;
    logic last = 0;
    logic [5*ACT_W-1:0] activations = '0;
    logic presence_rd_en, sign_rd_en;
    logic [AW-1:0] presence_rd_addr, sign_rd_addr;
    logic [4:0] presence_rd_data = '0;
    logic [7:0] sign_rd_data = '0;
    logic signed [ACC_W-1:0] dot;
    logic done;

    ternary_bitcos_stream5_bank_fed dut (
        .clk(clk), .rst_n(rst_n), .start(start),
        .start_presence_addr(start_presence_addr),
        .start_sign_bit_addr(start_sign_bit_addr),
        .valid(valid), .last(last), .activations(activations),
        .presence_rd_en(presence_rd_en), .presence_rd_addr(presence_rd_addr),
        .presence_rd_data(presence_rd_data),
        .sign_rd_en(sign_rd_en), .sign_rd_addr(sign_rd_addr),
        .sign_rd_data(sign_rd_data),
        .dot(dot), .done(done)
    );

    always #1 clk = ~clk;

    logic [4:0] pres_mem [0:MEMB-1];
    logic [7:0] sgn_mem [0:MEMB-1];
    logic [39:0] act_mem [0:MAXGROUPS-1];
    integer row_pword [0:MAXROWS-1];
    integer row_sbit [0:MAXROWS-1];
    integer row_groups [0:MAXROWS-1];
    integer row_act [0:MAXROWS-1];
    integer row_idle [0:MAXROWS-1];
    integer row_expected [0:MAXROWS-1];
    integer nrows, pptr, sptr, gptr, total_groups;
    integer checked, errors, xerrors, max_consec, run_sign, cycles_valid;
    integer i, r, g, so, zi, k;
    integer zp_list [0:4];

    // Memories: one synchronous read port each, output held between reads.
    always @(posedge clk) begin
        if (presence_rd_en === 1'b1)
            presence_rd_data <= pres_mem[presence_rd_addr];
        if (sign_rd_en === 1'b1)
            sign_rd_data <= sgn_mem[sign_rd_addr];
        if (rst_n && ((presence_rd_en !== 1'b0 && presence_rd_en !== 1'b1) ||
                      (sign_rd_en !== 1'b0 && sign_rd_en !== 1'b1) ||
                      (presence_rd_en === 1'b1 && $isunknown(presence_rd_addr)) ||
                      (sign_rd_en === 1'b1 && $isunknown(sign_rd_addr)))) begin
            if (xerrors < 10) $display("FAIL unknown read request at %0t", $time);
            xerrors = xerrors + 1;
        end
    end

    always @(negedge clk) begin
        if (rst_n) begin
            if (done) begin
                if (checked >= nrows) begin
                    $display("FAIL spurious done");
                    errors = errors + 1;
                end else if ($signed(dot) !== row_expected[checked]) begin
                    if (errors < 20)
                        $display("FAIL row %0d (pword %0d sbit %0d groups %0d) dot=%0d expected=%0d",
                                 checked, row_pword[checked], row_sbit[checked],
                                 row_groups[checked], $signed(dot), row_expected[checked]);
                    errors = errors + 1;
                end
                checked = checked + 1;
            end
            if (valid) cycles_valid = cycles_valid + 1;
            if (valid && sign_rd_en === 1'b1) begin
                run_sign = run_sign + 1;
                if (run_sign > max_consec) max_consec = run_sign;
            end else begin
                run_sign = 0;
            end
        end
    end

    task put_sign(input integer pos, input integer b);
        logic [7:0] t;
        begin
            t = sgn_mem[pos >> 3];
            t[pos & 7] = b[0];
            sgn_mem[pos >> 3] = t;
        end
    endtask

    // pjump: skip this many presence words first (garbage between rows).
    // soff < 0: continue the sign stream contiguously; otherwise skip ahead
    // to the next bit with that intra-byte offset.
    // mode 0: iid, P(zero) = zp/1000, random signs
    // mode 1: all nonzero, all negative
    // mode 2: groups alternate all-nonzero (random signs) / all-zero
    task add_row(input integer pjump, input integer soff, input integer groups,
                 input integer zp, input integer mode, input integer idle);
        integer gg, l, w, a, expv;
        logic [39:0] word;
        logic [4:0] pword;
        begin
            pptr = pptr + pjump;
            if (soff >= 0) sptr = sptr + ((soff - sptr) & 7);
            row_pword[nrows] = pptr;
            row_sbit[nrows] = sptr;
            row_groups[nrows] = groups;
            row_act[nrows] = gptr;
            row_idle[nrows] = idle;
            expv = 0;
            for (gg = 0; gg < groups; gg = gg + 1) begin
                word = '0;
                pword = '0;
                for (l = 0; l < 5; l = l + 1) begin
                    a = $urandom_range(255, 0) - 128;
                    word[l*8 +: 8] = a[7:0];
                    case (mode)
                        1: w = -1;
                        2: w = (gg % 2 == 0) ? (($urandom & 1) ? -1 : 1) : 0;
                        default: w = ($urandom_range(999, 0) < zp) ? 0 :
                                     (($urandom & 1) ? -1 : 1);
                    endcase
                    pword[l] = (w != 0);
                    if (w != 0) begin
                        put_sign(sptr, (w < 0));
                        sptr = sptr + 1;
                    end
                    expv = expv + w * a;
                end
                pres_mem[pptr] = pword;
                pptr = pptr + 1;
                act_mem[gptr] = word;
                gptr = gptr + 1;
            end
            row_expected[nrows] = expv;
            nrows = nrows + 1;
            total_groups = total_groups + groups;
        end
    endtask

    initial begin
        nrows = 0; pptr = 0; sptr = 0; gptr = 0; total_groups = 0;
        checked = 0; errors = 0; xerrors = 0;
        max_consec = 0; run_sign = 0; cycles_valid = 0;
        zp_list[0] = 0; zp_list[1] = 200; zp_list[2] = 420; zp_list[3] = 700; zp_list[4] = 1000;
        for (i = 0; i < MEMB; i = i + 1) begin
            pres_mem[i] = $urandom;
            sgn_mem[i] = $urandom;
        end

        // Every sign offset at every zero density.
        for (so = 0; so < 8; so = so + 1)
            for (zi = 0; zi < 5; zi = zi + 1)
                for (k = 0; k < 4; k = k + 1)
                    add_row($urandom_range(3, 0), so, 1 + $urandom_range(11, 0), zp_list[zi], 0, 0);
        // Maximum sign rate and extremes at every sign offset.
        for (so = 0; so < 8; so = so + 1) begin
            add_row($urandom_range(3, 0), so, 64, 0, 1, 0);
            add_row($urandom_range(3, 0), so, 64, 0, 0, 0);
            add_row($urandom_range(3, 0), so, 33, 0, 2, 0);
            add_row($urandom_range(3, 0), so, 64, 1000, 0, 0);
        end
        // Single-group rows back to back.
        for (k = 0; k < 40; k = k + 1)
            add_row($urandom_range(1, 0), $urandom_range(7, 0), 1,
                    zp_list[$urandom_range(4, 0)], 0, 0);
        // Contiguous streams, as in a real weight layout.
        for (k = 0; k < 300; k = k + 1)
            add_row(0, -1, 1 + $urandom_range(39, 0), zp_list[k % 5],
                    (k % 17 == 0) ? 1 : 0, (k % 7 == 3) ? $urandom_range(3, 1) : 0);
        if (pptr > MEMB - 4 || (sptr >> 3) > MEMB - 4) $fatal(1, "memory too small");

        repeat (2) @(posedge clk);
        #0.2 rst_n = 1;

        for (r = 0; r < nrows; r = r + 1) begin
            for (k = 0; k < row_idle[r]; k = k + 1) begin
                @(posedge clk);
                start <= 0; valid <= 0; last <= 0;
                start_presence_addr <= $urandom;
                start_sign_bit_addr <= $urandom;
                activations <= {$urandom, $urandom};
            end
            @(posedge clk);
            start <= 1; valid <= 0; last <= 0;
            start_presence_addr <= row_pword[r];
            start_sign_bit_addr <= row_sbit[r];
            activations <= {$urandom, $urandom};
            repeat (PREFILL) begin
                @(posedge clk);
                start <= 0;
                start_presence_addr <= $urandom;
                start_sign_bit_addr <= $urandom;
                activations <= {$urandom, $urandom};
            end
            for (g = 0; g < row_groups[r]; g = g + 1) begin
                @(posedge clk);
                start <= 0;
                valid <= 1;
                last <= (g == row_groups[r] - 1);
                activations <= act_mem[row_act[r] + g];
                start_presence_addr <= $urandom;
                start_sign_bit_addr <= $urandom;
            end
        end
        @(posedge clk);
        valid <= 0; last <= 0;
        repeat (3) @(posedge clk);

        $display("coverage: %0d rows, %0d groups, %0d valid cycles, longest run of sign-byte advances %0d",
                 nrows, total_groups, cycles_valid, max_consec);
        if (errors != 0 || xerrors != 0 || checked != nrows || cycles_valid != total_groups) begin
            $display("FAIL: %0d errors, %0d unknown requests, %0d of %0d rows checked",
                     errors, xerrors, checked, nrows);
            $finish(1);
        end
        $display("PASS: Architecture B bitmap/sign bank fed random, %0d rows", nrows);
        $finish(0);
    end
endmodule
