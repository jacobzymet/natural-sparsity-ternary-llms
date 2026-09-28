// PPA-oriented dense 2-bit baseline using per-lane add/zero/subtract selection
// and a shared balanced reduction tree rather than a serial accumulator chain.
module ternary_dense2_parallel_gemv #(
    parameter int LANES = 16,
    parameter int ACT_W = 8,
    parameter int ACC_W = 24
) (
    input  logic [LANES*ACT_W-1:0] activations,
    input  logic [LANES*2-1:0]     weights_2b,
    output logic signed [ACC_W-1:0] dot
);
    wire [LANES*ACC_W-1:0] contributions;

    genvar i;
    generate
        for (i = 0; i < LANES; i = i + 1) begin : gen_lane
            wire signed [ACT_W-1:0] a = $signed(activations[i*ACT_W +: ACT_W]);
            wire signed [ACC_W-1:0] a_ext = a;
            wire [1:0] code = weights_2b[i*2 +: 2];
            wire signed [ACC_W-1:0] contribution =
                (code == 2'b01) ? a_ext :
                (code == 2'b10) ? -a_ext :
                '0;
            assign contributions[i*ACC_W +: ACC_W] = contribution;
        end
    endgenerate

    signed_adder_tree #(.LANES(LANES), .ACC_W(ACC_W)) reduce (
        .inputs(contributions),
        .sum(dot)
    );
endmodule
