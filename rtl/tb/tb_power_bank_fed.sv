`timescale 1ns/1ps

// Trace-driven GEMV testbench for switching-activity measurement of the
// Architecture B bitmap/sign engine including its weight feed
// (ternary_bitcos_stream5_bank_fed). Works on RTL or on a flattened gate
// netlist.
//
// The presence (5-bit words) and sign (bytes) memories are behavioral (not
// part of the measured design): one synchronous read port each, data valid
// after the sampling edge and held until the next read. The presence words
// are repacked here from the same byte-packed bitmap the other engines read,
// so every engine sees identical weights.
//
// Plusargs: +DIR=<workload dir> +ROWS=<n> +GROUPS=<K/5> +PERIOD=<ns> [+VCD=<file>]
// Workload files come from scripts/power_workload.py.
module tb_power_bank_fed;
    localparam int AW = 16;
    localparam int PREFILL = 1;

    logic clk = 0;
    logic rst_n = 0;
    logic start = 0;
    logic [AW-1:0] start_presence_addr = '0;
    logic [AW+2:0] start_sign_bit_addr = '0;
    logic valid = 0;
    logic last = 0;
    logic [39:0] activations = '0;
    logic presence_rd_en, sign_rd_en;
    logic [AW-1:0] presence_rd_addr, sign_rd_addr;
    logic [4:0] presence_rd_data = '0;
    logic [7:0] sign_rd_data = '0;
    logic signed [23:0] dot;
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

    string dir;
    string vcd;
    integer rows, groups, r, g, i, j, bit_index, checked, errors;
    real period, drive;
    logic [39:0] acts [0:4095];
    logic [7:0] pres [0:262143];
    logic [4:0] bank [0:(1 << AW) - 1];
    logic [7:0] sgn [0:262143];
    logic [63:0] rowinfo [0:1023];

    initial begin
        period = 2.0;
        void'($value$plusargs("PERIOD=%f", period));
    end
    always #(period / 2.0) clk = ~clk;

    always @(posedge clk) begin
        if (presence_rd_en === 1'b1)
            presence_rd_data <= bank[presence_rd_addr];
        else if (rst_n && presence_rd_en !== 1'b0)
            presence_rd_data <= 'x;
        if (sign_rd_en === 1'b1)
            sign_rd_data <= sgn[sign_rd_addr];
        else if (rst_n && sign_rd_en !== 1'b0)
            sign_rd_data <= 'x;
    end

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
        for (i = 0; i < 262144; i = i + 1) begin
            pres[i] = 8'h00;
            sgn[i] = 8'h00;
        end
        $readmemh({dir, "/acts.memh"}, acts);
        $readmemh({dir, "/presence.memh"}, pres);
        $readmemh({dir, "/signs.memh"}, sgn);
        $readmemh({dir, "/rows.memh"}, rowinfo);
        if (rows * groups > (1 << AW)) $fatal(1, "presence bank too small");
        for (i = 0; i < rows * groups; i = i + 1)
            for (j = 0; j < 5; j = j + 1) begin
                bit_index = i * 5 + j;
                bank[i][j] = pres[bit_index >> 3][bit_index & 7];
            end
        drive = 0.1 * period;

        repeat (2) @(posedge clk);
        #(drive) rst_n = 1;
        if ($value$plusargs("VCD=%s", vcd)) begin
            $dumpfile(vcd);
            $dumpvars(2, dut);
        end

        // Inputs change with nonblocking assignments in the same time step as
        // the clock edge, as if driven by registers on the same clock (the
        // memory models' outputs included). Rows run back to back: start,
        // PREFILL idle cycles, GROUPS valid cycles. Row r's presence words
        // start at r*GROUPS; the sign stream start comes from rows.memh.
        for (r = 0; r < rows; r = r + 1) begin
            @(posedge clk);
            start <= 1; valid <= 0; last <= 0;
            start_presence_addr <= r * groups;
            start_sign_bit_addr <= rowinfo[r][AW+2:0];
            repeat (PREFILL) begin
                @(posedge clk);
                start <= 0;
            end
            for (g = 0; g < groups; g = g + 1) begin
                @(posedge clk);
                start <= 0;
                valid <= 1;
                last <= (g == groups - 1);
                activations <= acts[g];
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
        $display("PASS: Architecture B bitmap/sign fed power trace, %0d rows x %0d groups", rows, groups);
        $finish(0);
    end
endmodule
