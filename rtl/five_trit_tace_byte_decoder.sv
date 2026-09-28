// T-ACE-style two-stage 5-trit decoder for one packed byte.
//
// Based on Jung et al., ICS 2026, Section 3.2:
//   1. Compare P against {27,54,...,216}.
//   2. q = popcount(comparators) = floor(P / 27), q in [0,8].
//   3. A 9-entry LUT returns high trits (t4,t3) and base offset 27*q.
//   4. R = P - offset, R in [0,26].
//   5. A 27-entry LUT returns low trits (t2,t1,t0).
//
// Internal ternary code convention matches this repository:
//   2'b00 = 0, 2'b01 = +1, 2'b10 = -1.
// Base-3 digit convention: 0 -> 0, 1 -> +1, 2 -> -1.
module five_trit_tace_byte_decoder (
    input  logic [7:0] packed_byte,
    output logic [9:0] weights_2b
);
    logic [7:0] ge;
    logic [3:0] q;
    logic [7:0] offset;
    logic [7:0] remainder;
    logic [3:0] high_trits;
    logic [5:0] low_trits;

    always_comb begin
        ge[0] = (packed_byte >= 8'd27);
        ge[1] = (packed_byte >= 8'd54);
        ge[2] = (packed_byte >= 8'd81);
        ge[3] = (packed_byte >= 8'd108);
        ge[4] = (packed_byte >= 8'd135);
        ge[5] = (packed_byte >= 8'd162);
        ge[6] = (packed_byte >= 8'd189);
        ge[7] = (packed_byte >= 8'd216);

        q = ge[0] + ge[1] + ge[2] + ge[3]
          + ge[4] + ge[5] + ge[6] + ge[7];

        // {t4, t3} encoded as {dense2(t4), dense2(t3)}.
        // offset = 81*t4_digit + 27*t3_digit = 27*q.
        high_trits = 4'b0000;
        offset = 8'd0;
        case (q)
            4'd0: begin high_trits = {2'b00,2'b00}; offset = 8'd0;   end
            4'd1: begin high_trits = {2'b00,2'b01}; offset = 8'd27;  end
            4'd2: begin high_trits = {2'b00,2'b10}; offset = 8'd54;  end
            4'd3: begin high_trits = {2'b01,2'b00}; offset = 8'd81;  end
            4'd4: begin high_trits = {2'b01,2'b01}; offset = 8'd108; end
            4'd5: begin high_trits = {2'b01,2'b10}; offset = 8'd135; end
            4'd6: begin high_trits = {2'b10,2'b00}; offset = 8'd162; end
            4'd7: begin high_trits = {2'b10,2'b01}; offset = 8'd189; end
            4'd8: begin high_trits = {2'b10,2'b10}; offset = 8'd216; end
            default: begin high_trits = 4'b0000; offset = 8'd0; end
        endcase

        remainder = packed_byte - offset;

        // {t2,t1,t0}, with t0 in weights_2b[1:0].
        low_trits = 6'b000000;
        case (remainder)
            8'd0:  low_trits = {2'b00,2'b00,2'b00};
            8'd1:  low_trits = {2'b00,2'b00,2'b01};
            8'd2:  low_trits = {2'b00,2'b00,2'b10};
            8'd3:  low_trits = {2'b00,2'b01,2'b00};
            8'd4:  low_trits = {2'b00,2'b01,2'b01};
            8'd5:  low_trits = {2'b00,2'b01,2'b10};
            8'd6:  low_trits = {2'b00,2'b10,2'b00};
            8'd7:  low_trits = {2'b00,2'b10,2'b01};
            8'd8:  low_trits = {2'b00,2'b10,2'b10};
            8'd9:  low_trits = {2'b01,2'b00,2'b00};
            8'd10: low_trits = {2'b01,2'b00,2'b01};
            8'd11: low_trits = {2'b01,2'b00,2'b10};
            8'd12: low_trits = {2'b01,2'b01,2'b00};
            8'd13: low_trits = {2'b01,2'b01,2'b01};
            8'd14: low_trits = {2'b01,2'b01,2'b10};
            8'd15: low_trits = {2'b01,2'b10,2'b00};
            8'd16: low_trits = {2'b01,2'b10,2'b01};
            8'd17: low_trits = {2'b01,2'b10,2'b10};
            8'd18: low_trits = {2'b10,2'b00,2'b00};
            8'd19: low_trits = {2'b10,2'b00,2'b01};
            8'd20: low_trits = {2'b10,2'b00,2'b10};
            8'd21: low_trits = {2'b10,2'b01,2'b00};
            8'd22: low_trits = {2'b10,2'b01,2'b01};
            8'd23: low_trits = {2'b10,2'b01,2'b10};
            8'd24: low_trits = {2'b10,2'b10,2'b00};
            8'd25: low_trits = {2'b10,2'b10,2'b01};
            8'd26: low_trits = {2'b10,2'b10,2'b10};
            default: low_trits = 6'b000000;
        endcase

        weights_2b = {high_trits, low_trits};
    end
endmodule
