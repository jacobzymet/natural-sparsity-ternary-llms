`timescale 1ns/1ps

module tb_bitcos_stream5;
    localparam int ACT_W = 8;
    localparam int ACC_W = 24;

    logic clk = 0;
    logic rst_n = 0;
    logic start = 0;
    logic [2:0] initial_offset = 0;
    logic valid = 0;
    logic last = 0;
    logic [5*ACT_W-1:0] activations = 0;
    logic [4:0] presence = 0;
    logic [7:0] current_sign_byte = 0;
    logic [7:0] next_sign_byte = 0;
    logic advance_sign_byte;
    logic [2:0] sign_offset;
    logic signed [ACC_W-1:0] dot;
    logic done;

    integer off;
    integer p;
    integer pat;
    integer lane;
    integer rank;
    integer expected_consumed;
    integer sum;
    reg [15:0] pair;
    reg [9:0] expected_weights;
    reg sign_bit;

    logic [9:0] decoder_weights;
    logic [2:0] decoder_consumed;
    logic [2:0] decoder_offset;
    logic decoder_advance_byte;
    logic decoder_start = 0;
    logic decoder_advance = 0;
    logic [2:0] decoder_initial_offset = 0;
    logic [4:0] decoder_presence = 0;
    logic [7:0] decoder_current = 0;
    logic [7:0] decoder_next = 0;

    ternary_bitcos_stream5_accum #(.ACT_W(ACT_W), .ACC_W(ACC_W)) dut (
        .clk(clk), .rst_n(rst_n), .start(start),
        .initial_sign_offset(initial_offset), .valid(valid), .last(last),
        .activations(activations), .presence(presence),
        .current_sign_byte(current_sign_byte), .next_sign_byte(next_sign_byte),
        .advance_sign_byte(advance_sign_byte), .sign_offset(sign_offset),
        .dot(dot), .done(done)
    );

    bitcos_stream5_bytecursor_decoder decoder (
        .clk(clk), .rst_n(rst_n), .start_block(decoder_start),
        .initial_offset(decoder_initial_offset), .advance(decoder_advance),
        .current_sign_byte(decoder_current), .next_sign_byte(decoder_next),
        .presence(decoder_presence), .weights_2b(decoder_weights),
        .consumed_signs(decoder_consumed), .offset_state(decoder_offset),
        .advance_sign_byte(decoder_advance_byte)
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

    task load_decoder_offset(input integer value);
        begin
            decoder_initial_offset = value[2:0];
            decoder_start = 1;
            decoder_advance = 0;
            @(posedge clk); #0.1;
            decoder_start = 0;
        end
    endtask

    initial begin
        #2;
        rst_n = 1;

        // Exhaustively cover all offsets/presence patterns with varied signs.
        for (off = 0; off < 8; off = off + 1) begin
            for (p = 0; p < 32; p = p + 1) begin
                for (pat = 0; pat < 256; pat = pat + 29) begin
                    load_decoder_offset(off);
                    decoder_current = pat[7:0];
                    decoder_next = ~pat[7:0];
                    decoder_presence = p[4:0];
                    #0.1;

                    pair = {decoder_next, decoder_current};
                    expected_weights = 0;
                    rank = 0;
                    expected_consumed = 0;
                    for (lane = 0; lane < 5; lane = lane + 1) begin
                        if (decoder_presence[lane]) begin
                            sign_bit = pair[off + rank];
                            expected_weights[lane*2 +: 2] =
                                sign_bit ? 2'b10 : 2'b01;
                            rank = rank + 1;
                            expected_consumed = expected_consumed + 1;
                        end
                    end

                    if (decoder_weights !== expected_weights) begin
                        $display("FAIL decoder weights off=%0d p=%h pat=%h", off, p, pat);
                        $finish(1);
                    end
                    if (decoder_consumed !== expected_consumed[2:0]) begin
                        $display("FAIL decoder consumed off=%0d p=%h", off, p);
                        $finish(1);
                    end

                    sum = off + expected_consumed;
                    decoder_advance = 1;
                    #0.1;
                    if (decoder_advance_byte !== (sum >= 8)) begin
                        $display("FAIL decoder byte advance off=%0d p=%h", off, p);
                        $finish(1);
                    end
                    @(posedge clk); #0.1;
                    decoder_advance = 0;
                    if (decoder_offset !== (sum & 7)) begin
                        $display("FAIL decoder offset off=%0d p=%h got=%0d expected=%0d",
                                 off, p, decoder_offset, (sum & 7));
                        $finish(1);
                    end
                end
            end
        end

        // Throughput-matched row test. Same ten weights used by the T-ACE
        // streaming test: [ +1,0,-1,+1,0 | 0,-1,+1,0,+1 ].
        // compact signs = [+, -, +, -, +, +] = 0b001010.
        current_sign_byte = 8'h0A;
        next_sign_byte = 8'h00;
        initial_offset = 0;
        start = 1;
        @(posedge clk); #0.1;
        start = 0;

        set_acts(1,2,3,4,5);
        presence = 5'b01101;
        valid = 1;
        last = 0;
        @(posedge clk); #0.1;

        set_acts(6,7,8,9,10);
        presence = 5'b10110;
        last = 1;
        @(posedge clk); #0.1;
        valid = 0;
        last = 0;

        if (!done || $signed(dot) !== 13) begin
            $display("FAIL stream5 dot=%0d done=%b", $signed(dot), done);
            $finish(1);
        end

        $display("PASS: five-position BITCOS byte-cursor stream");
        $finish(0);
    end
endmodule
