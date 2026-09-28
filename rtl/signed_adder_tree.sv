// Balanced reduction tree for LANES signed ACC_W-bit inputs.
// Supports non-power-of-two lane counts by propagating unmatched nodes.
module signed_adder_tree #(
    parameter int LANES = 16,
    parameter int ACC_W = 24,
    parameter int STAGES = (LANES <= 1) ? 0 : $clog2(LANES)
) (
    input  logic [LANES*ACC_W-1:0] inputs,
    output logic signed [ACC_W-1:0] sum
);
    wire signed [ACC_W-1:0] stage [0:STAGES][0:LANES-1];

    genvar i;
    generate
        for (i = 0; i < LANES; i = i + 1) begin : gen_input
            assign stage[0][i] = $signed(inputs[i*ACC_W +: ACC_W]);
        end
    endgenerate

    genvar s;
    genvar j;
    generate
        for (s = 0; s < STAGES; s = s + 1) begin : gen_stage
            for (j = 0; j < LANES; j = j + 1) begin : gen_lane
                if ((j % (1 << (s + 1))) == 0) begin : gen_root
                    if ((j + (1 << s)) < LANES) begin : gen_pair
                        assign stage[s+1][j] = stage[s][j] + stage[s][j + (1 << s)];
                    end else begin : gen_unpaired
                        assign stage[s+1][j] = stage[s][j];
                    end
                end else begin : gen_inactive
                    assign stage[s+1][j] = '0;
                end
            end
        end
    endgenerate

    generate
        if (LANES == 1) begin : gen_single
            assign sum = stage[0][0];
        end else begin : gen_multi
            assign sum = stage[STAGES][0];
        end
    endgenerate
endmodule
