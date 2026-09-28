`timescale 1ns/1ps

`ifndef DIRECT_TOP
`define DIRECT_TOP ternary_bitcos_stream5_direct_accum
`endif

module tb_bitcos_stream5_direct;
    localparam int ACT_W = 8;
    localparam int ACC_W = 24;

    logic clk = 0;
    logic rst_n = 0;
    logic start = 0;
    logic [2:0] initial_presence_offset = 0;
    logic [2:0] initial_sign_offset = 0;
    logic valid = 0;
    logic last = 0;
    logic [5*ACT_W-1:0] activations = 0;
    logic [7:0] current_presence_byte = 0;
    logic [7:0] next_presence_byte = 0;
    logic [7:0] current_sign_byte = 0;
    logic [7:0] next_sign_byte = 0;
    logic advance_presence_byte;
    logic advance_sign_byte;
    logic [2:0] presence_offset;
    logic [2:0] sign_offset;
    logic signed [ACC_W-1:0] dot;
    logic done;
    integer off, mask, idx, sign_rank, expected, a;
    logic [15:0] bitmap_word;

    `DIRECT_TOP #(
        .ACT_W(ACT_W), .ACC_W(ACC_W)
    ) dut (
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

    always #1 clk = ~clk;

    task set_acts(
        input integer a0, input integer a1, input integer a2,
        input integer a3, input integer a4
    );
        begin
            activations[0*ACT_W +: ACT_W] = a0[7:0];
            activations[1*ACT_W +: ACT_W] = a1[7:0];
            activations[2*ACT_W +: ACT_W] = a2[7:0];
            activations[3*ACT_W +: ACT_W] = a3[7:0];
            activations[4*ACT_W +: ACT_W] = a4[7:0];
        end
    endtask

    initial begin
        #2;
        rst_n = 1;

        // Ten positions:
        // [ +1,0,-1,+1,0 | 0,-1,+1,0,+1 ]
        //
        // Presence bits, contiguous by position:
        // first 5 = 01101, second 5 = 10110
        // lower ten bitmap bits = 10'b10110_01101 = 0x2CD.
        current_presence_byte = 8'hCD;
        next_presence_byte = 8'h02;

        // Nonzero signs:
        // [+, -, +, -, +, +] => 0b001010 in compact order.
        current_sign_byte = 8'h0A;
        next_sign_byte = 8'h00;

        start = 1;
        @(posedge clk); #0.1;
        start = 0;

        set_acts(1,2,3,4,5);
        valid = 1;
        last = 0;
        @(posedge clk); #0.1;

        if (presence_offset !== 5 || sign_offset !== 3) begin
            $display("FAIL offsets after group1 presence=%0d sign=%0d",
                     presence_offset, sign_offset);
            $finish(1);
        end

        set_acts(6,7,8,9,10);
        last = 1;
        #0.1;
        if (!advance_presence_byte) begin
            $display("FAIL expected presence byte advance on group2");
            $finish(1);
        end
        @(posedge clk); #0.1;
        valid = 0;
        last = 0;

        if (!done || $signed(dot) !== 13) begin
            $display("FAIL full-front stream dot=%0d done=%b", $signed(dot), done);
            $finish(1);
        end
        if (presence_offset !== 2 || sign_offset !== 6) begin
            $display("FAIL final offsets presence=%0d sign=%0d",
                     presence_offset, sign_offset);
            $finish(1);
        end

        // Every presence pattern and every starting bit offset. The sign
        // pattern crosses byte boundaries in the high-offset cases.
        for (off = 0; off < 8; off = off + 1) begin
            for (mask = 0; mask < 32; mask = mask + 1) begin
                valid = 0;
                last = 0;
                initial_presence_offset = off[2:0];
                initial_sign_offset = off[2:0];
                bitmap_word = mask << off;
                current_presence_byte = bitmap_word[7:0];
                next_presence_byte = bitmap_word[15:8];
                current_sign_byte = 8'h96;
                next_sign_byte = 8'hA5;
                start = 1;
                @(posedge clk); #0.1;
                start = 0;

                set_acts(1,-2,3,-4,5);
                sign_rank = 0;
                expected = 0;
                for (idx = 0; idx < 5; idx = idx + 1) begin
                    case (idx)
                        0: a = 1;
                        1: a = -2;
                        2: a = 3;
                        3: a = -4;
                        default: a = 5;
                    endcase
                    if ((mask >> idx) & 1) begin
                        if ((16'hA596 >> (off + sign_rank)) & 1)
                            expected = expected - a;
                        else
                            expected = expected + a;
                        sign_rank = sign_rank + 1;
                    end
                end
                valid = 1;
                last = 1;
                @(posedge clk); #0.1;
                if (!done || $signed(dot) !== expected) begin
                    $display("FAIL direct dot off=%0d mask=%0d got=%0d expected=%0d",
                             off, mask, $signed(dot), expected);
                    $finish(1);
                end
            end
        end

        $display("PASS: five-position direct BITCOS stream");
        $finish(0);
    end
endmodule
