module tb_five_trit_tace_exhaustive;
    logic [7:0] packed_byte;
    logic [9:0] weights_2b;
    integer p;
    integer q;
    integer digit;
    integer lane;
    logic [9:0] expected;

    five_trit_tace_byte_decoder dut (
        .packed_byte(packed_byte),
        .weights_2b(weights_2b)
    );

    initial begin
        for (p = 0; p <= 242; p = p + 1) begin
            packed_byte = p[7:0];
            expected = '0;
            q = p;
            for (lane = 0; lane < 5; lane = lane + 1) begin
                digit = q % 3;
                case (digit)
                    0: expected[lane*2 +: 2] = 2'b00;
                    1: expected[lane*2 +: 2] = 2'b01;
                    2: expected[lane*2 +: 2] = 2'b10;
                endcase
                q = q / 3;
            end
            #1;
            if (weights_2b !== expected) begin
                $display("T-ACE decoder mismatch P=%0d got=%b expected=%b",
                         p, weights_2b, expected);
                $fatal(1);
            end
        end

        $display("T-ACE exhaustive 243-byte decoder test passed");
        $finish;
    end
endmodule
