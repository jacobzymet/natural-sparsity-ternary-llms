// Five-position BITCOS presence/sign decode.
//
// sign_window contains the next five compact signs in nonzero order.
// sign bit 0 = +1, sign bit 1 = -1.
// output ternary code: 00 = 0, 01 = +1, 10 = -1.
module bitcos_group5_decode (
    input  logic [4:0] presence,
    input  logic [4:0] sign_window,
    output logic [9:0] weights_2b,
    output logic [2:0] consumed_signs
);
    integer i;
    integer rank;

    always_comb begin
        weights_2b = '0;
        consumed_signs = '0;
        rank = 0;

        for (i = 0; i < 5; i = i + 1) begin
            if (presence[i]) begin
                weights_2b[i*2 +: 2] =
                    sign_window[rank] ? 2'b10 : 2'b01;
                rank = rank + 1;
                consumed_signs = consumed_signs + 1'b1;
            end
        end
    end
endmodule
